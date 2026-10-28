"""parsewright CLI: run a job, then approve and promote its add-on.

parsewright run <file>                    build and test a TA through all three stages
parsewright status <job>                  show a run record
parsewright approve <job> --sha256 <hash> approve exactly the validated package
parsewright promote <job>                 install the approved TA under its real names
"""

import argparse
import json
import sys
from pathlib import Path

from parsewright.agents.llm import LLMClient, TokenCeilingExceeded
from parsewright.config import REPO, Settings, load_env_file
from parsewright.guardrails.index_time import GuardrailBlock
from parsewright.orchestrator import promote
from parsewright.orchestrator.caps import IngestCaps
from parsewright.orchestrator.run import MAX_ATTEMPTS, run
from parsewright.tools.splunk_client import SplunkClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="parsewright")
    # The repo's .env, not the working directory's: a planted .env could redirect the tokens.
    parser.add_argument("--env-file", type=Path, default=REPO / ".env")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="build and test a TA for one log file (all three stages)")
    r.add_argument("file", type=Path)
    r.add_argument("--tz", help="timezone of the logs, if known (IANA name)")
    r.add_argument("--vendor", help="vendor name, if known (e.g. acme)")
    r.add_argument("--product", help="product name, if known (e.g. vpn)")
    r.add_argument("--keep", action="store_true", help="leave the test app installed")
    r.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    r.add_argument("--stages", default="index-time,extraction,cim", help="comma-separated")
    s = sub.add_parser("status", help="show a run record")
    s.add_argument("job")
    a = sub.add_parser("approve", help="approve exactly the validated package")
    a.add_argument("job")
    a.add_argument("--sha256", required=True)
    p = sub.add_parser("promote", help="install the approved TA under its real names")
    p.add_argument("job")
    args = parser.parse_args(argv)

    load_env_file(args.env_file)
    settings = Settings.from_env()
    try:
        if args.command == "run":
            caps = IngestCaps(settings.runs_dir, settings.job_ingest_mb, settings.daily_ingest_mb)
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
                runs_dir=settings.runs_dir,
                caps=caps,
            )
            return 0 if result.status == "passed" else 1
        if args.command == "status":
            record = promote.load(settings.runs_dir, args.job)
            print(json.dumps({k: v for k, v in record.items() if k != "events"}, indent=1))
            for e in record.get("events", []):
                print(f"  {e['at']} {e['event']}")
            return 0
        if args.command == "approve":
            print(promote.approve(settings.runs_dir, args.job, args.sha256))
            return 0
        record = promote.promote(
            settings.runs_dir,
            args.job,
            SplunkClient(settings),
            settings.packages_dir,
            settings.test_index,
            caps=IngestCaps(settings.runs_dir, settings.job_ingest_mb, settings.daily_ingest_mb),
        )
        return 0 if record["status"] == promote.DONE else 1
    except TokenCeilingExceeded as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 3
    except (promote.TransitionRefused, GuardrailBlock, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
