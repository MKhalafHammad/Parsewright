"""commit-msg hook: reject AI attribution in commit messages.

Git passes the message file before stripping comments, so comment lines
(e.g. "# On branch ..." or "# new file: CLAUDE.md") are ignored here.
"""

import re
import sys

FORBIDDEN = re.compile(r"co-authored-by|claude|anthropic|generated with", re.IGNORECASE)
SCISSORS = "# ------------------------ >8 ------------------------"


def message_lines(text: str) -> list[str]:
    body = text.split(SCISSORS, 1)[0]
    return [line for line in body.splitlines() if not line.startswith("#")]


def main(path: str) -> int:
    with open(path, encoding="utf-8") as f:
        hits = [line for line in message_lines(f.read()) if FORBIDDEN.search(line)]
    if not hits:
        return 0
    print(
        "Commit rejected: the message must not mention AI attribution", file=sys.stderr
    )
    print(
        "(Co-Authored-By, Claude, Anthropic, Generated with). Offending lines:",
        file=sys.stderr,
    )
    for line in hits:
        print(f"  {line}", file=sys.stderr)
    print("See CLAUDE.md, 'Non-negotiable rules'.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
