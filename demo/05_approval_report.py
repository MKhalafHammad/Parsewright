"""RECORD THIS: the approval report (Phase 6). Run through demo/05_approval_report.sh.

Uploads the prompt-injection fixture (one line carries an injected instruction and a <script>
tag) with profile review skipped, waits until it awaits approval, then prints the page to open:
raw vs parsed with highlights, the mapping table, CIM scores and configs; the <script> line shows
as plain text. Approve there and download the .tgz.
"""

import os
import sys
import time
from pathlib import Path

import httpx

API = os.environ.get("PARSEWRIGHT_API", "http://127.0.0.1:8080")
UI = os.environ.get("PARSEWRIGHT_UI", "http://localhost:3000")
FX = Path(__file__).resolve().parents[1] / "engine/parsewright/generator/fixtures"


def main() -> int:
    c = httpx.Client(base_url=API, timeout=60, headers={"X-Parsewright": "1"})
    name = "acme_vpn_injected.json"
    files = {
        "file": (name, (FX / name).read_bytes()),
        "manifest": (
            "acme_vpn_injected.manifest.json",
            (FX / "acme_vpn_injected.manifest.json").read_bytes(),
        ),
    }
    r = c.post(
        "/uploads",
        files=files,
        data={"vendor": "acme", "product": "vpnreport", "auto_approve": "true"},
    )
    r.raise_for_status()
    job = r.json()["job"]
    print(
        f"job {job}{' (already known)' if r.json()['duplicate'] else ''}: following it live at "
        f"{UI}/runs/{job}"
    )
    while (status := c.get(f"/runs/{job}").json()["status"]) in ("queued", "running"):
        print(time.strftime("%H:%M:%S"), status)
        time.sleep(10)
    print(f"{job}: {status}. Open {UI}/runs/{job} for the approval report.")
    return 0 if status == "awaiting_approval" else 1


if __name__ == "__main__":
    sys.exit(main())
