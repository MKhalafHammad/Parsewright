"""Create .env from .env.example if missing, and replace every placeholder password with a random
one. Never prints a secret; reports only which keys it generated and which still need a value.

Usage: python3 scripts/init_env.py
"""

import os
import re
import secrets
import string
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV, EXAMPLE = ROOT / ".env", ROOT / ".env.example"
# Letters and digits only: docker-compose puts these into connection URLs (see .env.example).
GENERATED = ("SPLUNK_PASSWORD", "POSTGRES_PASSWORD", "POSTGRES_APP_PASSWORD")
PLACEHOLDER = re.compile(r"^(changeme|your-).*")


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
    if not ENV.exists():
        write_private(ENV, EXAMPLE.read_text())
        print("created .env from .env.example")
    os.chmod(ENV, 0o600)
    alphabet = string.ascii_letters + string.digits
    lines, made = [], []
    for line in ENV.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key in GENERATED and PLACEHOLDER.match(value.strip()):
            line = f"{key}={''.join(secrets.choice(alphabet) for _ in range(32))}"
            made.append(key)
        lines.append(line)
    write_private(ENV, "\n".join(lines) + "\n")
    if made:
        print(f"generated: {', '.join(made)}")
    values = dict(
        ln.partition("=")[::2] for ln in lines if "=" in ln and not ln.startswith("#")
    )
    if PLACEHOLDER.match(values.get("LLM_API_KEY", "").strip()) or not values.get(
        "LLM_API_KEY"
    ):
        print(
            "LLM_API_KEY is still a placeholder: set your Meta Model API key in .env",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
