"""Worker: claims jobs from PostgreSQL and runs them with the shared orchestrator.

- Claims with FOR UPDATE SKIP LOCKED; a heartbeat renews the ~2 min lease; a worker that loses
  its lease stops before its next Splunk write.
- Checkpoints after the profile, each attempt and each passed stage, so another worker can resume
  a crashed job from the last saved state.
- A job waiting for profile review is released; the worker takes the next one.
- Splunk writes run under one cluster-wide lock; model calls share a fixed number of slots;
  the daily token budget and the kill switch stop new work and new model calls.
"""

import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from parsewright.agents.llm import LLMClient
from parsewright.agents.profiler import clean_name
from parsewright.config import Settings, database_url
from parsewright.ledger import store as db
from parsewright.orchestrator import promote
from parsewright.orchestrator.caps import IngestCaps
from parsewright.orchestrator.run import STAGES, RunAborted, run
from parsewright.tools.splunk_client import SplunkClient

HEARTBEAT_S = 30
LLM_SLOTS = 2


class BudgetStop(RuntimeError):
    pass


class Worker:
    def __init__(
        self,
        settings: Settings,
        worker_id: str,
        out: Callable[[str], None] = print,
        splunk: SplunkClient | None = None,
        llm_factory: Callable[[], LLMClient] | None = None,
        daily_tokens: int = 2_000_000,
    ):
        self.settings, self.id, self.out = settings, worker_id, out
        self.conn = db.connect(database_url())
        self.store = db.Store(self.conn)
        self.splunk = splunk or SplunkClient(settings)
        self.llm_factory = llm_factory or (lambda: LLMClient(settings))
        self.daily_tokens = daily_tokens
        self.stages = STAGES
        # Separate connections: the heartbeat thread and model-call slots must not share the
        # main connection's transactions.
        self.side = db.Store(db.connect(database_url()))

    # --- loop --------------------------------------------------------------------------

    def run_forever(self, stop: threading.Event, idle: float = 2.0) -> None:
        while not stop.is_set():
            if not self.once():
                stop.wait(idle)

    def once(self, only: str | None = None) -> bool:
        """Claim and process one job. False if there was nothing to do (or work is stopped)."""
        if self.store.kill_switch():
            return False
        if self.store.tokens_today() >= self.daily_tokens:
            return False
        job = self.store.claim(self.id, only=only)
        if job is None:
            return False
        with self.heartbeat(job["id"]) as lost:
            try:
                if job["status"] == "promoting":
                    self.promote(job)
                else:
                    self.build(job, lost)
            except RunAborted as e:
                self.out(f"[{self.id}] {job['id']}: stopped ({e})")
            except Exception as e:  # noqa: BLE001 - any crash ends this job, never the worker
                self.store.event(job["id"], "error", {"error": type(e).__name__})
                self.store.transition(job["id"], db.WORKING, "error", worker=self.id)
                self.out(f"[{self.id}] {job['id']}: error {type(e).__name__}: {e}")
        return True

    @contextmanager
    def heartbeat(self, job: str):
        lost: dict[str, str] = {}
        done = threading.Event()

        conn = db.connect(database_url())  # the thread's own connection

        def beat() -> None:
            beats = db.Store(conn)
            while not done.wait(HEARTBEAT_S):
                try:
                    beats.heartbeat(job, self.id)
                except db.LostLease as e:
                    lost["reason"] = str(e)
                    return
                except Exception as e:  # noqa: BLE001 - a dead heartbeat must stop the work
                    lost["reason"] = f"heartbeat failed: {type(e).__name__}"
                    return

        thread = threading.Thread(target=beat, daemon=True)
        thread.start()
        try:
            yield lost
        finally:
            done.set()
            thread.join(timeout=5)
            conn.close()

    # --- building a TA -------------------------------------------------------------------

    def build(self, job: dict, lost: dict) -> None:
        jid, form, state = job["id"], job["form"], job["state"] or {}
        llm = self.llm_factory()
        llm.guard = self.model_call_guard
        llm.on_usage = lambda n: self.side.add_tokens(jid, n)
        records = promote.PgRecords(self.conn, self.settings.runs_dir, worker=self.id)
        result = run(
            Path(job["sample_path"]),
            llm,
            self.splunk,
            self.settings.test_index,
            self.settings.packages_dir,
            out=lambda line: self.log(jid, line),
            timezone=form.get("tz"),
            vendor=form.get("vendor"),
            product=form.get("product"),
            caps=IngestCaps(
                self.settings.runs_dir, self.settings.job_ingest_mb, self.settings.daily_ingest_mb
            ),
            job=jid,
            state=state,
            checkpoint=lambda s: self.store.checkpoint(jid, self.id, s),
            review=not form.get("auto_approve") and not state.get("profile_confirmed"),
            lock=lambda: self.store.advisory(db.SPLUNK_WRITE_LOCK),
            abort=lambda: (
                lost.get("reason") or ("kill switch on" if self.side.kill_switch() else None)
            ),
            record=lambda j, pkg, **kw: promote.record_passed_run(records, j, pkg, **kw),
            stages=self.stages,
        )
        if result.status == "profile_review":
            self.store.transition(jid, "running", "profile_review", worker=self.id, worker_id=None)
        elif result.status != "passed" or self.stages != STAGES:
            # A full passing run already moved to awaiting_approval with its record.
            final = "stage_failed" if result.status != "passed" else "done"
            self.store.transition(jid, "running", final, worker=self.id)
        self.out(f"[{self.id}] {jid}: {result.status}")

    @contextmanager
    def model_call_guard(self):
        if self.side.kill_switch():
            raise RunAborted("kill switch on")
        if self.side.tokens_today() >= self.daily_tokens:
            raise RunAborted("daily token budget reached")
        with self.side.llm_slot(LLM_SLOTS):
            if self.side.kill_switch():  # switched on while this call waited for a slot (L6)
                raise RunAborted("kill switch on")
            yield

    # --- promotion -----------------------------------------------------------------------

    def promote(self, job: dict) -> None:
        records = promote.PgRecords(self.conn, self.settings.runs_dir, worker=self.id)
        record = promote.promote(
            records,
            job["id"],
            self.splunk,
            self.settings.packages_dir,
            self.settings.test_index,
            caps=IngestCaps(
                self.settings.runs_dir, self.settings.job_ingest_mb, self.settings.daily_ingest_mb
            ),
            out=lambda line: self.log(job["id"], line),
            start=promote.PROMOTING,
        )
        self.out(f"[{self.id}] {job['id']}: {record['status']}")

    def log(self, job: str, line: str) -> None:
        self.store.event(job, "log", {"line": line[:2000]})
        self.out(f"[{self.id}] {job}: {line}")


def apply_corrections(profile: dict, corrections: dict) -> dict:
    """A human's profile-review corrections: data, validated like every other input."""
    from parsewright.guardrails.index_time import ALLOWED

    out = dict(profile)
    for field in ("vendor", "product", "sourcetype"):
        if corrections.get(field):
            out[field] = clean_name(str(corrections[field]))
    if corrections.get("tz"):
        ALLOWED["TZ"](str(corrections["tz"]))
        out["timezone_hint"] = str(corrections["tz"])
    return out


def wait_for_db(dsn: str, seconds: float = 60) -> None:
    end = time.monotonic() + seconds
    while True:
        try:
            db.connect(dsn).close()
            return
        except Exception:  # keep trying until the deadline
            if time.monotonic() > end:
                raise
            time.sleep(2)
