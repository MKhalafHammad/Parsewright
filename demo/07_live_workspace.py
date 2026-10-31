"""RECORD THIS: the agent-centred run workspace. Run through demo/07_live_workspace.sh.

Uploads the no-offset VPN fixture (Tokyo time, no timezone in the timestamps) with profile review
on, prints the board and the job's workspace, then follows the job until it awaits approval.
Confirm the profile in the UI (leave the timezone empty to watch Index-time find it, or set it).
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
    name = "acme_vpn_notz.json"
    files = {
        "file": (name, (FX / name).read_bytes()),
        "manifest": (
            "acme_vpn_notz.manifest.json",
            (FX / "acme_vpn_notz.manifest.json").read_bytes(),
        ),
    }
    r = c.post("/uploads", files=files, data={"vendor": "acme", "product": "vpnlive"})
    r.raise_for_status()
    job = r.json()["job"]
    print(f"job {job}{' (already known)' if r.json()['duplicate'] else ''}")
    print(f"  board:     {UI}/")
    print(f"  workspace: {UI}/runs/{job}")
    last = ""
    while (status := c.get(f"/runs/{job}").json()["status"]) not in (
        "awaiting_approval",
        "stage_failed",
        "error",
        "rejected",
        "done",
    ):
        if status != last:
            print(time.strftime("%H:%M:%S"), status)
            if status == "profile_review":
                print("  confirm the profile in the workspace to continue")
            last = status
        time.sleep(5)
    print(
        f"{job}: {status}. Every phase and attempt is at {UI}/runs/{job}?phase=<phase>&attempt=<n>"
    )
    return 0 if status == "awaiting_approval" else 1


if __name__ == "__main__":
    sys.exit(main())
