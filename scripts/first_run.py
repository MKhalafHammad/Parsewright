"""Start the first run on a fresh stack: uploads the bundled synthetic VPN log and its truth
manifest to the engine (published on 127.0.0.1 only), then follows the job until it awaits
approval. Standard library only, so a judge needs no virtualenv.

Usage: python3 scripts/first_run.py   (or `make first-run`)
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FX = ROOT / "engine/parsewright/generator/fixtures"
API = os.environ.get("PARSEWRIGHT_API", "http://127.0.0.1:8080")
UI = os.environ.get("PARSEWRIGHT_UI", "http://localhost:3000")
FINAL = {"awaiting_approval", "stage_failed", "error", "rejected", "done"}


def request(
    method: str, path: str, body: bytes | None = None, ctype: str | None = None
) -> dict:
    req = urllib.request.Request(API + path, data=body, method=method)
    req.add_header("X-Parsewright", "1")
    if ctype:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 - http(s) checked in main
        return json.loads(r.read())


def multipart(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        )
    for k, p in files.items():
        head = f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{p.name}"\r\n'
        parts.append(
            head.encode()
            + b"Content-Type: application/octet-stream\r\n\r\n"
            + p.read_bytes()
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    if not API.startswith(("http://", "https://")):
        print("PARSEWRIGHT_API must be an http(s) URL", file=sys.stderr)
        return 1
    body, ctype = multipart(
        {"vendor": "acme", "product": "vpn", "auto_approve": "true"},
        {"file": FX / "acme_vpn.json", "manifest": FX / "acme_vpn.manifest.json"},
    )
    try:
        r = request("POST", "/uploads", body, ctype)
    except urllib.error.URLError as e:
        print(
            f"the engine is not reachable at {API} ({e}); is `make up` finished?",
            file=sys.stderr,
        )
        return 1
    job = r["job"]
    print(
        f"job {job}{' (already known)' if r.get('duplicate') else ''}: follow it at {UI}/runs/{job}"
    )
    last = ""
    while (status := request("GET", f"/runs/{job}")["status"]) not in FINAL:
        if status != last:
            print(time.strftime("%H:%M:%S"), status)
            last = status
        time.sleep(5)
    print(
        f"{job}: {status}. Open {UI}/runs/{job}"
        + (" to review and approve." if status == "awaiting_approval" else ".")
    )
    return 0 if status in ("awaiting_approval", "done") else 1


if __name__ == "__main__":
    sys.exit(main())
