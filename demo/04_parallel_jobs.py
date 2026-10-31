"""RECORD THIS: parallel jobs (Phase 5). Run through demo/04_parallel_jobs.sh.

Uploads four fixtures at once; three run straight through while the fourth (no auto-approve)
pauses for profile review and frees its worker; then confirms that profile and it resumes.
"""

import os
import sys
import time
from pathlib import Path

import httpx

API = os.environ.get("PARSEWRIGHT_API", "http://127.0.0.1:8080")
FX = Path(__file__).resolve().parents[1] / "engine/parsewright/generator/fixtures"
UPLOADS = [
    ("acme_vpn.json", "acme", "vpn", {"auto_approve": "true"}),
    ("acme_fw.log", "acme", "fwdemo", {"auto_approve": "true"}),
    ("acme_proxy.csv", "acme", "proxydemo", {"auto_approve": "true"}),
    ("acme_ssh.log", "acme", "bastion", {"tz": "UTC"}),  # pauses for profile review
]
DONE = {"awaiting_approval", "stage_failed", "error", "done", "rejected"}


def main() -> int:
    # The API refuses state changes without this header (CSRF protection, threat T8.3).
    c = httpx.Client(base_url=API, timeout=60, headers={"X-Parsewright": "1"})
    jobs = []
    for name, vendor, product, extra in UPLOADS:
        files = {
            "file": (name, (FX / name).read_bytes()),
            "manifest": (
                f"{Path(name).stem}.manifest.json",
                (FX / f"{Path(name).stem}.manifest.json").read_bytes(),
            ),
        }
        r = c.post(
            "/uploads",
            files=files,
            data={"vendor": vendor, "product": product, **extra},
        )
        r.raise_for_status()
        body = r.json()
        print(
            f"uploaded {name}: job {body['job']} (~{body['estimated_tokens']} tokens)"
            + (" [duplicate of an existing job]" if body["duplicate"] else "")
        )
        jobs.append(body["job"])
    review, confirmed = jobs[3], False
    while True:
        states = {j: c.get(f"/runs/{j}").json()["status"] for j in jobs}
        print(
            time.strftime("%H:%M:%S"), "  ".join(f"{j}:{s}" for j, s in states.items())
        )
        if states[review] == "profile_review" and not confirmed:
            running = [j for j, s in states.items() if s == "running"]
            print(
                f">>> {review} waits for profile review while {len(running)} others keep "
                "running; confirming it"
            )
            c.post(f"/runs/{review}/profile", json={"tz": "UTC"}).raise_for_status()
            confirmed = True
        if all(s in DONE for s in states.values()):
            break
        time.sleep(10)
    for j in jobs:
        run = c.get(f"/runs/{j}").json()
        print(
            f"{j}: {run['status']}, {run['tokens']} tokens, sha256 "
            f"{run['record'].get('sha256_test', '-')}"
        )
    return 0 if all(s == "awaiting_approval" for s in states.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
