"""Set KEY=VALUE pairs read from stdin in .env (mode 600), replacing existing lines.

Used by scripts/up.sh to store the Splunk tokens the bootstrap creates, so they never reach the
terminal. Only the SPLUNK_*_TOKEN keys are accepted. Prints the key names it set, never values.
"""

import os
import re
import sys
import tempfile
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"
ALLOWED = re.compile(r"^SPLUNK_(SEARCH|DEPLOY|DRIFT)_TOKEN$")
VALUE = re.compile(r"^[A-Za-z0-9._-]{20,4096}$")  # a JWT: no spaces, quotes or newlines


def write_private(path: Path, text: str) -> None:
    """Write `path` atomically, never readable by others, even for a moment."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".env.")  # created 0600
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main() -> int:
    os.umask(0o077)
    pairs = {}
    for raw in sys.stdin.read().splitlines():
        key, sep, value = raw.strip().partition("=")
        if not sep:
            continue
        if not ALLOWED.match(key) or not VALUE.match(value):
            print(f"refused a value for {key[:40]!r}", file=sys.stderr)
            return 1
        pairs[key] = value
    lines, seen = [], set()
    for line in ENV.read_text().splitlines():
        key = line.partition("=")[0]
        if key in pairs:
            line, _ = f"{key}={pairs[key]}", seen.add(key)
        lines.append(line)
    lines += [f"{k}={v}" for k, v in pairs.items() if k not in seen]
    write_private(ENV, "\n".join(lines) + "\n")
    print(f"stored in .env: {', '.join(sorted(pairs)) or 'nothing'}")
    return 0 if pairs else 1


if __name__ == "__main__":
    sys.exit(main())
