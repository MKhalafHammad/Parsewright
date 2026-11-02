"""RECORD THIS: just the log, no answer key (post-Phase 7). Run through demo/08_log_only.sh.

fw        (default) a fresh firewall log, nothing else. The agents do all the work; the
          Validator proves on every event, with no manifest, that each time equals the time
          written in its line and every value is exactly as written. The report lists the
          agents' decisions (timestamp reading, field meanings, value -> CIM value with counts).
timezone  a fresh VPN log in local time with no zone. Nothing in the file proves the zone, so
          the run pauses in profile review and asks; confirm Asia/Tokyo there and it goes on.

Each batch has a seed from the clock, so it is never a generator fixture (those are recognised
and checked against their known answers) and never a duplicate.
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


def fresh(folder: Path, mode: str) -> Path:
    synth.FIXTURES = (
        folder  # write into the temp folder, never over the committed fixtures
    )
    seed = int(time.time())
    if mode == "timezone":
        synth.write(
            "vpn_local",
            "json",
            synth.vpn_events(120, seed),
            synth.vpn_line,
            "Asia/Tokyo",
            "demo",
        )
        log = folder / "vpn_local.json"
    else:
        synth.write(
            "fw_live", "log", synth.fw_events(240, seed), synth.fw_line, None, "demo"
        )
        log = folder / "fw_live.log"
    log.with_suffix(
        ".manifest.json"
    ).unlink()  # the answer key never leaves this script
    return log


def main(mode: str) -> int:
    c = httpx.Client(base_url=API, timeout=60, headers={"X-Parsewright": "1"})
    with tempfile.TemporaryDirectory() as tmp:
        log = fresh(Path(tmp), mode)
        r = c.post(
            "/uploads",
            files={"file": (log.name, log.read_bytes())},  # only the log, nothing else
            data={"auto_approve": "true"},
        )
    r.raise_for_status()
    job = r.json()["job"]
    if r.json()["duplicate"]:
        print(f"this exact log is already job {job}: {UI}/runs/{job}")
        return 1
    print(f"job {job}: only the log was uploaded; following it at {UI}/runs/{job}")
    while (run := c.get(f"/runs/{job}").json())["status"] in ("queued", "running"):
        print(time.strftime("%H:%M:%S"), run["status"], f"{run['tokens']} tokens")
        time.sleep(10)
    print(f"{job}: {run['status']}, {run['tokens']} tokens")
    if run["status"] == "profile_review":
        print(
            f"The timestamps carry no zone. Open {UI}/runs/{job}, choose the timezone "
            "(Asia/Tokyo) and confirm; the run then continues on its own."
        )
    report = (run.get("record") or {}).get("report") or {}
    if decisions := report.get("decisions"):
        ts = decisions["timestamp"]
        print(
            f"validated: {report.get('validation')}; timestamp {ts['time_format']} "
            f"tz {ts['tz'] or 'from each timestamp'}; first event {ts['first_raw'][:60]!r}"
        )
        for v in decisions["values"]:
            if v.get("identity"):
                pairs = f"copied unchanged ({v['distinct']} distinct values)"
            else:
                pairs = ", ".join(
                    f"{p['from']} -> {p['to']} ({p['count']})" for p in v["pairs"]
                )
            print(f"  {v['cim_field']} from {v['from']}: {pairs}")
        print(f"Open {UI}/runs/{job}: check the decisions, then approve.")
    return 0 if run["status"] in ("awaiting_approval", "profile_review") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "fw"))
