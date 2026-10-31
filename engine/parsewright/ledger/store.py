"""PostgreSQL job queue, run state and append-only ledger (design "Concurrency").

Every query is parameterised. Every state change is `UPDATE ... WHERE status = <expected>`
with the row count checked, so a replayed or racing request changes nothing.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MIGRATIONS = Path(__file__).parent / "migrations"
LEASE_S = 120
# Statuses a worker can pick up: new work, resumable work whose lease expired, approvals.
CLAIMABLE = ("queued", "approved")
WORKING = ("running", "promoting")
# Final statuses that free a content hash / a source key for a new job (migration 002).
FREE_CONTENT = ("rejected", "stage_failed", "error", "smoke_failed", "promotion_failed")
FREE_SOURCE = (*FREE_CONTENT, "done")
# Advisory lock keys (cluster-wide): Splunk writes, and a pool of LLM slots.
SPLUNK_WRITE_LOCK = 7001
LLM_SLOT_BASE = 7100


class LostLease(RuntimeError):
    """This worker no longer owns the job (lease expired and another worker took it)."""


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn, row_factory=dict_row, autocommit=True, connect_timeout=10)


def set_app_password(conn: psycopg.Connection, password: str) -> None:
    """Give the engine's limited role its password (from POSTGRES_APP_PASSWORD)."""
    from psycopg import sql

    # DDL takes no bound parameters, so the password is quoted by psycopg's sql.Literal; only
    # `parsewright migrate` (the owner account) runs this. The rule targets SQLAlchemy text.
    statement = sql.SQL("ALTER ROLE parsewright_app PASSWORD {}").format(sql.Literal(password))
    conn.execute(statement)  # nosemgrep


def migrate(conn: psycopg.Connection) -> list[str]:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
    done = {r["name"] for r in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (path.name,))
        applied.append(path.name)
    return applied


class Store:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    # --- intake ------------------------------------------------------------------------

    def enqueue(
        self, job: str, source_key: str, sha256: str, sample_path: str, form: dict
    ) -> tuple[str, bool]:
        """Insert a queued job, or return the active job with the same content or source key."""
        try:
            with self.conn.transaction():
                self.conn.execute(
                    "INSERT INTO jobs (id, status, source_key, content_sha256, sample_path, form)"
                    " VALUES (%s, 'queued', %s, %s, %s, %s)",
                    (job, source_key, sha256, sample_path, Jsonb(form)),
                )
                self.event(job, "queued", {"source_key": source_key})
            return job, False
        except psycopg.errors.UniqueViolation:
            # Mirrors the two partial unique indexes exactly (migration 002).
            row = self.conn.execute(
                "SELECT id FROM jobs WHERE (content_sha256 = %s AND NOT (status = ANY(%s)))"
                " OR (source_key = %s AND NOT (status = ANY(%s)))"
                " ORDER BY created_at LIMIT 1",
                (sha256, list(FREE_CONTENT), source_key, list(FREE_SOURCE)),
            ).fetchone()
            if row is None:
                raise
            return row["id"], True

    # --- claiming and leases --------------------------------------------------------------

    def claim(self, worker: str, only: str | None = None) -> dict | None:
        """Atomically take one job: queued or approved, or working with an expired lease."""
        row = self.conn.execute(
            """
            WITH next AS (
                SELECT id, status FROM jobs
                WHERE (status = ANY(%(claimable)s)
                       OR (status = ANY(%(working)s) AND lease_until < now()))
                  AND (%(only)s::text IS NULL OR id = %(only)s)
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE jobs SET
                status = CASE WHEN next.status IN ('approved', 'promoting') THEN 'promoting'
                              ELSE 'running' END,
                worker_id = %(worker)s,
                lease_until = now() + make_interval(secs => %(lease)s),
                updated_at = now()
            FROM next WHERE jobs.id = next.id
            RETURNING jobs.*, next.status AS claimed_from
            """,
            {
                "claimable": list(CLAIMABLE),
                "working": list(WORKING),
                "only": only,
                "worker": worker,
                "lease": LEASE_S,
            },
        ).fetchone()
        if row:
            self.event(row["id"], "claimed", {"worker": worker, "from": row["claimed_from"]})
        return row

    def heartbeat(self, job: str, worker: str) -> None:
        cur = self.conn.execute(
            "UPDATE jobs SET lease_until = now() + make_interval(secs => %s), updated_at = now()"
            " WHERE id = %s AND worker_id = %s AND status = ANY(%s)",
            (LEASE_S, job, worker, list(WORKING)),
        )
        if cur.rowcount != 1:
            raise LostLease(f"{worker} no longer holds {job}")

    def transition(
        self,
        job: str,
        expected: str | tuple[str, ...],
        new: str,
        worker: str | None = None,
        **fields: Any,
    ) -> bool:
        """UPDATE ... WHERE status = expected (and owner); True only if exactly one row moved.

        One fixed statement: each optional field is set only when its flag is true, so no SQL is
        ever built from strings."""
        expected = (expected,) if isinstance(expected, str) else expected
        unknown = set(fields) - {"state", "record", "worker_id", "lease_until"}
        if unknown:
            raise ValueError(f"unknown job field {', '.join(sorted(unknown))}")
        params = {
            "new": new,
            "job": job,
            "expected": list(expected),
            "worker": worker,
            "set_state": "state" in fields,
            "state": Jsonb(fields.get("state")),
            "set_record": "record" in fields,
            "record": Jsonb(fields.get("record")),
            "set_worker_id": "worker_id" in fields,
            "worker_id": fields.get("worker_id"),
            "set_lease": "lease_until" in fields,
            "lease_until": fields.get("lease_until"),
        }
        cur = self.conn.execute(
            """
            UPDATE jobs SET
                status = %(new)s,
                updated_at = now(),
                state = CASE WHEN %(set_state)s THEN %(state)s ELSE state END,
                record = CASE WHEN %(set_record)s THEN %(record)s ELSE record END,
                worker_id = CASE WHEN %(set_worker_id)s THEN %(worker_id)s::text
                                 ELSE worker_id END,
                lease_until = CASE WHEN %(set_lease)s THEN %(lease_until)s::timestamptz
                                   ELSE lease_until END
            WHERE id = %(job)s AND status = ANY(%(expected)s)
              AND (%(worker)s::text IS NULL OR worker_id = %(worker)s)
            """,
            params,
        )
        if cur.rowcount == 1:
            self.event(job, "state", {"from": list(expected), "to": new})
            return True
        return False

    def checkpoint(self, job: str, worker: str, state: dict) -> None:
        """Save the run's progress before the next step (resume point after a crash)."""
        cur = self.conn.execute(
            "UPDATE jobs SET state = %s, updated_at = now()"
            " WHERE id = %s AND worker_id = %s AND status = 'running'",
            (Jsonb(state), job, worker),
        )
        if cur.rowcount != 1:
            raise LostLease(f"{worker} no longer holds {job}")

    # --- reads -------------------------------------------------------------------------

    def get(self, job: str) -> dict | None:
        return self.conn.execute("SELECT * FROM jobs WHERE id = %s", (job,)).fetchone()

    def jobs(self, limit: int = 100) -> list[dict]:
        return self.conn.execute(
            "SELECT id, status, source_key, form, tokens, created_at, updated_at FROM jobs"
            " ORDER BY created_at DESC LIMIT %s",
            (limit,),
        ).fetchall()

    # --- ledger ------------------------------------------------------------------------

    def event(self, job: str, event: str, data: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO ledger (job_id, event, data) VALUES (%s, %s, %s)",
            (job, event, Jsonb(data or {})),
        )

    def events(self, job: str, after: int = 0, limit: int = 500) -> list[dict]:
        return self.conn.execute(
            "SELECT id, at, event, data FROM ledger WHERE job_id = %s AND id > %s"
            " ORDER BY id LIMIT %s",
            (job, after, limit),
        ).fetchall()

    # --- budgets and switches -----------------------------------------------------------

    def add_tokens(self, job: str, n: int) -> None:
        with self.conn.transaction():
            self.conn.execute("UPDATE jobs SET tokens = tokens + %s WHERE id = %s", (n, job))
            self.conn.execute(
                "INSERT INTO usage (day, tokens) VALUES (%s, %s)"
                " ON CONFLICT (day) DO UPDATE SET tokens = usage.tokens + EXCLUDED.tokens",
                (datetime.now(UTC).date(), n),
            )

    def tokens_today(self) -> int:
        row = self.conn.execute(
            "SELECT tokens FROM usage WHERE day = %s", (datetime.now(UTC).date(),)
        ).fetchone()
        return int(row["tokens"]) if row else 0

    def kill_switch(self) -> bool:
        row = self.conn.execute("SELECT value FROM settings WHERE key = 'kill_switch'").fetchone()
        return bool(row and row["value"] is True)

    def set_kill_switch(self, on: bool) -> None:
        self.conn.execute(
            "UPDATE settings SET value = %s WHERE key = 'kill_switch'", (Jsonb(bool(on)),)
        )

    # --- TA registry (migration 003) ---------------------------------------------------

    def ta(self, app: str) -> dict | None:
        return self.conn.execute("SELECT * FROM tas WHERE app = %s", (app,)).fetchone()

    def tas(self) -> list[dict]:
        return self.conn.execute(
            "SELECT t.*, (SELECT json_agg(v.version ORDER BY v.created_at) FROM ta_versions v"
            " WHERE v.app = t.app) AS versions FROM tas t ORDER BY t.app"
        ).fetchall()

    def ta_versions(self, app: str) -> list[dict]:
        """Every version, oldest first, with the job that built it (its samples and profile)."""
        return self.conn.execute(
            "SELECT v.version, v.job_id, v.sha256, v.created_at, j.sample_path,"
            " j.content_sha256, j.form->>'manifest_sha256' AS manifest_sha256,"
            " j.state->'profile' AS profile FROM ta_versions v JOIN jobs j ON j.id = v.job_id"
            " WHERE v.app = %s ORDER BY v.created_at, v.version",
            (app,),
        ).fetchall()

    def register_ta(self, record: dict, version: str, sha256: str) -> None:
        """A newly promoted TA and its first version."""
        with self.conn.transaction():
            self.conn.execute(
                "INSERT INTO tas (app, sourcetype, vendor, product, owner_job, current_version)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    record["app"],
                    record["sourcetype"],
                    record["vendor"],
                    record["product"],
                    record["job"],
                    version,
                ),
            )
            self.conn.execute(
                "INSERT INTO ta_versions (app, version, job_id, sha256) VALUES (%s, %s, %s, %s)",
                (record["app"], version, record["job"], sha256),
            )
            self.ta_event(record["app"], "registered", {"version": version, "job": record["job"]})

    def add_version(self, app: str, previous: str, version: str, job: str, sha256: str) -> None:
        """An update's new version; refused unless the registry is still at `previous`."""
        with self.conn.transaction():
            self.conn.execute(
                "INSERT INTO ta_versions (app, version, job_id, sha256) VALUES (%s, %s, %s, %s)",
                (app, version, job, sha256),
            )
            self.set_current_version(app, previous, version, "updated", {"job": job})

    def set_current_version(
        self, app: str, previous: str, version: str, event: str, data: dict | None = None
    ) -> None:
        cur = self.conn.execute(
            "UPDATE tas SET current_version = %s, updated_at = now()"
            " WHERE app = %s AND current_version = %s",
            (version, app, previous),
        )
        if cur.rowcount != 1:
            raise RuntimeError(f"{app} is no longer at version {previous}")
        self.ta_event(app, event, {"from": previous, "to": version, **(data or {})})

    def ta_event(self, app: str, event: str, data: dict | None = None) -> None:
        self.conn.execute(
            "INSERT INTO ta_events (app, event, data) VALUES (%s, %s, %s)",
            (app, event, Jsonb(data or {})),
        )

    # --- cluster-wide locks -------------------------------------------------------------

    @contextmanager
    def advisory(self, key: int) -> Iterator[None]:
        self.conn.execute("SELECT pg_advisory_lock(%s)", (key,))
        try:
            yield
        finally:
            self.conn.execute("SELECT pg_advisory_unlock(%s)", (key,))

    @contextmanager
    def ta_lock(self, app: str) -> Iterator[None]:
        """One promotion or rollback of a TA at a time, across every process (appsec M2)."""
        self.conn.execute("SELECT pg_advisory_lock(hashtext(%s))", (f"ta:{app}",))
        try:
            yield
        finally:
            self.conn.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"ta:{app}",))

    @contextmanager
    def llm_slot(self, slots: int) -> Iterator[None]:
        """One of `slots` model-call slots across every worker process."""
        while True:
            for k in range(LLM_SLOT_BASE, LLM_SLOT_BASE + slots):
                if self.conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (k,)).fetchone()[
                    "ok"
                ]:
                    try:
                        yield
                    finally:
                        self.conn.execute("SELECT pg_advisory_unlock(%s)", (k,))
                    return
            self.conn.execute("SELECT pg_sleep(0.5)")


def as_json(row: dict) -> str:
    return json.dumps(row, default=str)
