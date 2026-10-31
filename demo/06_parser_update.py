"""RECORD THIS: a parser update (Phase 7). Run through demo/06_parser_update.sh.

patch     (default) firmware v2 samples (src renamed src_ip, ISO 8601 timestamps instead of
          epoch milliseconds) against a promoted firewall TA. Diagnose finds the failing
          stages with no model call, only those stages are patched, every attempt is checked
          on the old and the new samples, and the report shows the diff against production.
diagnose  after the update is approved and promoted: a fresh batch of v2 events. The TA now
          parses them as it is, so the job ends at Diagnose having spent 0 tokens.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

import httpx
from parsewright.generator import synth

API = os.environ.get("PARSEWRIGHT_API", "http://127.0.0.1:8080")
UI = os.environ.get("PARSEWRIGHT_UI", "http://localhost:3000")
FX = Path(__file__).resolve().parents[1] / "engine/parsewright/generator/fixtures"


def fresh_v2(folder: Path) -> tuple[Path, Path]:
    """A new v2 batch (a seed from the clock, so the content is never a duplicate)."""
    synth.FIXTURES = (
        folder  # write into the temp folder, never over the committed fixtures
    )
    seed = int(time.time())
    synth.write(
        "acme_fw_v2_batch",
        "log",
        synth.fw_v2_events(120, seed),
        synth.fw_v2_line,
        None,
        f"fresh firmware v2 batch, seed {seed}",
    )
    return folder / "acme_fw_v2_batch.log", folder / "acme_fw_v2_batch.manifest.json"


def main(mode: str, app: str) -> int:
    c = httpx.Client(base_url=API, timeout=60, headers={"X-Parsewright": "1"})
    tas = {t["app"]: t for t in c.get("/tas").json()}
    if app not in tas:
        print(
            f"{app} is not in the TA registry; registered: {', '.join(tas) or 'none'}"
        )
        return 1
    print(f"{app}: production version {tas[app]['current_version']}")
    with tempfile.TemporaryDirectory() as tmp:
        if mode == "diagnose":
            log, manifest = fresh_v2(Path(tmp))
        else:
            log, manifest = FX / "acme_fw_v2.log", FX / "acme_fw_v2.manifest.json"
        r = c.post(
            "/uploads",
            files={
                "file": (log.name, log.read_bytes()),
                "manifest": (manifest.name, manifest.read_bytes()),
            },
            data={"update_of": app},
        )
    r.raise_for_status()
    job = r.json()["job"]
    note = " (already known)" if r.json()["duplicate"] else ""
    print(f"update job {job}{note}: following it live at {UI}/runs/{job}")
    while (run := c.get(f"/runs/{job}").json())["status"] in ("queued", "running"):
        print(time.strftime("%H:%M:%S"), run["status"], f"{run['tokens']} tokens")
        time.sleep(10)
    print(
        f"{job}: {run['status']} {run['record'].get('result', '')}, {run['tokens']} tokens"
    )
    if run["status"] == "awaiting_approval":
        print(
            f"Open {UI}/runs/{job}: the diff against production, then approve to update in place."
        )
    return 0 if run["status"] in ("awaiting_approval", "done") else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    mode = args[0] if args and args[0] in ("patch", "diagnose") else "patch"
    rest = args[1:] if args and args[0] in ("patch", "diagnose") else args
    sys.exit(main(mode, rest[0] if rest else "TA-parsewright-acme-fwdemo"))
