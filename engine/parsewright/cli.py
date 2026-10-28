"""parsewright CLI. Phase 2: `parsewright run <file>` runs the index-time stage end to end."""

import argparse
import sys
from pathlib import Path

from parsewright.agents.llm import LLMClient, TokenCeilingExceeded
from parsewright.config import Settings, load_env_file
from parsewright.orchestrator.run import MAX_ATTEMPTS, run
from parsewright.tools.splunk_client import SplunkClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="parsewright")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser(
        "run", help="build and test a TA for one log file (index-time, extraction, CIM)"
    )
    r.add_argument("file", type=Path)
    r.add_argument("--tz", help="timezone of the logs, if known (IANA name)")
    r.add_argument("--vendor", help="vendor name, if known (e.g. acme)")
    r.add_argument("--product", help="product name, if known (e.g. vpn)")
    r.add_argument("--keep", action="store_true", help="leave the test app installed")
    r.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    r.add_argument("--stages", default="index-time,extraction,cim", help="comma-separated")
    # The repo's .env, not the working directory's: a planted .env could redirect the tokens.
    r.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[2] / ".env")
    args = parser.parse_args(argv)

    load_env_file(args.env_file)
    settings = Settings.from_env()
    try:
        result = run(
            args.file,
            LLMClient(settings),
            SplunkClient(settings),
            settings.test_index,
            settings.packages_dir,
            timezone=args.tz,
            vendor=args.vendor,
            product=args.product,
            keep=args.keep,
            max_attempts=args.max_attempts,
            stages=tuple(args.stages.split(",")),
        )
    except TokenCeilingExceeded as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 3
    return 0 if result.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
