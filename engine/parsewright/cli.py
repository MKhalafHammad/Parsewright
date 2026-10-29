"""parsewright CLI. The CLI and the API share one orchestrator and one PostgreSQL queue.

  parsewright run <file>                    queue a job and process it here (auto-approved profile)
  parsewright status <job>                  show a run
  parsewright approve <job> --sha256 <hash> approve exactly the validated package
  parsewright promote <job>                 install the approved TA under its real names
  parsewright worker [--id w1]              run one worker
  parsewright serve [--workers 4]           run the API and a pool of workers
  parsewright kill on|off                   the kill switch: stop claims and model calls
  parsewright tas                           the TA registry: promoted TAs and their versions
  parsewright update <app> <file>           patch a promoted TA for new-format samples
  parsewright rollback <app> <version>      reinstall an exact earlier version of a TA

`run --local` runs without PostgreSQL (state in run records), as in Phases 2-4.
"""

import argparse
import json
import os
import signal
import subprocess  # nosec B404 - only to start this CLI's own worker processes
import sys
import threading
import uuid
from pathlib import Path

from parsewright.agents.llm import LLMClient, TokenCeilingExceeded
from parsewright.api import intake
from parsewright.config import REPO, Settings, database_url, load_env_file
from parsewright.guardrails.index_time import GuardrailBlock
from parsewright.ledger import store as db
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
    r.add_argument("--keep", action="store_true", help="leave the test app installed (--local)")
    r.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS)
    r.add_argument("--stages", default="index-time,extraction,cim", help="comma-separated")
    r.add_argument(
        "--local",
        action="store_true",
        help="no PostgreSQL: state in run records; the kill switch and daily budget do not apply",
    )
    s = sub.add_parser("status", help="show a run")
    s.add_argument("job")
    a = sub.add_parser("approve", help="approve exactly the validated package")
    a.add_argument("job")
    a.add_argument("--sha256", required=True)
    p = sub.add_parser("promote", help="install the approved TA under its real names")
    p.add_argument("job")
    w = sub.add_parser("worker", help="run one worker")
    w.add_argument("--id", default=f"w-{uuid.uuid4().hex[:6]}")
    w.add_argument("--parent", type=int, help="exit when this process (serve) is gone")
    v = sub.add_parser("serve", help="run the API and a pool of workers")
    v.add_argument("--workers", type=int, default=4)
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8080)
    sub.add_parser("migrate", help="apply migrations and set the app role's password (owner)")
    k = sub.add_parser("kill", help="the kill switch")
    k.add_argument("state", choices=["on", "off", "status"])
    sub.add_parser("tas", help="the TA registry")
    u = sub.add_parser("update", help="patch a promoted TA for new-format samples")
    u.add_argument("app")
    u.add_argument("file", type=Path)
    b = sub.add_parser("rollback", help="reinstall an exact earlier version of a promoted TA")
    b.add_argument("app")
    b.add_argument("version")
    args = parser.parse_args(argv)

    load_env_file(args.env_file)
    if args.command == "migrate":  # needs only the database owner, not the LLM or Splunk
        migrate()
        return 0
    settings = Settings.from_env()
    try:
        if args.command == "run" and args.local:
            return local_run(args, settings)
        if args.command == "serve":
            migrate(optional=True)  # inside docker-compose the "migrate" service did this
            return serve(args)
        conn = db.connect(database_url())
        store = db.Store(conn)
        records = promote.PgRecords(conn, settings.runs_dir)
        if args.command == "run":
            return queued_run(args, settings, store)
        if args.command == "update":
            return queued_run(args, settings, store, update_of=args.app)
        if args.command == "tas":
            for t in store.tas():
                print(
                    f"{t['app']}  {t['sourcetype']}  current {t['current_version']}  "
                    f"versions {', '.join(t['versions'] or [])}"
                )
            return 0
        if args.command == "rollback":
            print(
                promote.rollback(
                    store,
                    settings.runs_dir,
                    args.app,
                    args.version,
                    SplunkClient(settings),
                    settings.packages_dir,
                )
            )
            return 0
        if args.command == "status":
            row = store.get(args.job)
            if row is None:
                print(f"no job {args.job}", file=sys.stderr)
                return 4
            print(
                json.dumps({k: row[k] for k in ("id", "status", "source_key", "tokens")}, indent=1)
            )
            print(
                json.dumps(
                    {k: v for k, v in (row["record"] or {}).items() if k != "events"}, indent=1
                )
            )
            for e in store.events(args.job):
                if e["event"] != "log":
                    print(f"  {e['at']:%Y-%m-%dT%H:%M:%S} {e['event']} {json.dumps(e['data'])}")
            return 0
        if args.command == "approve":
            print(promote.approve(records, args.job, args.sha256))
            return 0
        if args.command == "promote":
            from parsewright.orchestrator.worker import Worker

            if store.get(args.job) is None or store.get(args.job)["status"] != "approved":
                raise promote.TransitionRefused("run is not approved")
            Worker(settings, f"cli-{uuid.uuid4().hex[:6]}").once(only=args.job)
            row = store.get(args.job)
            print(f"{args.job}: {row['status']} {row['record'].get('smoke', '')}")
            return 0 if row["status"] == promote.DONE else 1
        if args.command == "worker":
            from parsewright.orchestrator.worker import Worker

            stop = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stop.set())
            if args.parent:  # an orphaned worker must not keep claiming jobs unsupervised
                threading.Thread(target=watch_parent, args=(args.parent, stop), daemon=True).start()
            print(f"worker {args.id} started")
            Worker(settings, args.id).run_forever(stop)
            return 0
        if args.state != "status":
            store.set_kill_switch(args.state == "on")
        print(
            f"kill switch: {'on' if store.kill_switch() else 'off'}; "
            f"tokens today {store.tokens_today()}"
        )
        return 0
    except TokenCeilingExceeded as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 3
    except (promote.TransitionRefused, GuardrailBlock, intake.UploadRefused, ValueError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 4


def watch_parent(pid: int, stop: threading.Event) -> None:
    while not stop.wait(5):
        if os.getppid() != pid:
            stop.set()


def migrate(optional: bool = False) -> None:
    """The only use of the owner account: schema changes and the app role's password."""
    try:
        admin = database_url(admin=True)
    except RuntimeError:
        if optional:
            print("migrations: skipped (no owner credentials here; run `parsewright migrate`)")
            return
        raise
    with db.connect(admin) as conn:
        applied = db.migrate(conn)
        if password := os.environ.get("POSTGRES_APP_PASSWORD"):
            db.set_app_password(conn, password)
            print("migrations:", applied or "up to date", "| app role: parsewright_app")
        else:
            print(
                "migrations:",
                applied or "up to date",
                "| WARNING: POSTGRES_APP_PASSWORD not set; the engine uses the owner account",
            )


def queued_run(args, settings: Settings, store: db.Store, update_of: str | None = None) -> int:
    """Queue the file like an upload (same checks), then process exactly that job here."""
    from parsewright.orchestrator.worker import Worker

    sample = intake.check(args.file.read_bytes())
    manifest = args.file.with_suffix(".manifest.json").read_bytes()
    form: dict = {"auto_approve": True}
    if update_of:
        if store.ta(update_of) is None:
            raise promote.TransitionRefused(f"{update_of} is not in the TA registry")
        form["update_of"] = update_of
        key = f"update:{update_of}"
    else:
        for name in ("vendor", "product", "tz"):
            if getattr(args, name):
                form[name] = getattr(args, name)
        key = (
            f"{form['vendor']}:{form['product']}"
            if "vendor" in form and "product" in form
            else f"cli:{sample.sha256[:16]}"
        )
    job = uuid.uuid4().hex[:8]
    # A private copy, as for uploads: the samples stay the regression set of later updates,
    # and a path outside the runs folder could be swapped for a link (appsec Phase 7 M1).
    uploads = promote.runs_root(settings.runs_dir) / "uploads"
    uploads.mkdir(mode=0o700, exist_ok=True)
    path, form["manifest_sha256"] = intake.save(uploads, job, sample, manifest)
    job, duplicate = store.enqueue(job, key, sample.sha256, str(path), form)
    if duplicate:
        row = store.get(job)
        print(f"duplicate of job {job} ({row['status']}): nothing to do")
        return 0
    print(f"job {job} queued (~{intake.estimate_tokens(sample)} tokens estimated)")
    Worker(settings, f"cli-{uuid.uuid4().hex[:6]}").once(only=job)
    row = store.get(job)
    print(f"{job}: {row['status']} {row['record'].get('result', '')}".rstrip())
    if row["status"] == "awaiting_approval":
        print(f"approve: parsewright approve {job} --sha256 {row['record']['sha256_test']}")
    return 0 if row["status"] in ("awaiting_approval", "done") else 1


def local_run(args, settings: Settings) -> int:
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


def serve(args) -> int:
    """The API (uvicorn) plus a pool of worker processes; workers restart if they exit."""
    import uvicorn

    from parsewright.api.app import create_app

    me = [sys.executable, "-m", "parsewright.cli", "--env-file", str(args.env_file)]

    def start(name: str) -> subprocess.Popen:
        # Fixed arguments: this CLI's own interpreter and module, a generated worker id.
        argv = [*me, "worker", "--id", f"{name}-{os.getpid()}", "--parent", str(os.getpid())]
        return subprocess.Popen(argv)  # noqa: S603  # nosec B603

    procs = {f"w{i}": start(f"w{i}") for i in range(1, args.workers + 1)}
    stop = threading.Event()

    def supervise() -> None:
        while not stop.wait(5):
            for name, proc in list(procs.items()):
                if proc.poll() is not None:  # auto-restart policy (design "Operation never stops")
                    procs[name] = start(name)

    threading.Thread(target=supervise, daemon=True).start()
    try:
        uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=False)
    finally:
        stop.set()
        for proc in procs.values():
            proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
