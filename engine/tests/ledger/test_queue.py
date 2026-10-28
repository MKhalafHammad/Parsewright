"""Queue, leases, state transitions and the append-only ledger, against real PostgreSQL."""

import threading
import uuid

import psycopg
import pytest

from parsewright.ledger import store as db
from parsewright.orchestrator import promote


def job_id() -> str:
    return uuid.uuid4().hex[:8]


def enqueue(pg, n: int = 1) -> list[str]:
    ids = []
    for i in range(n):
        j = job_id()
        pg.enqueue(j, f"src:{j}", f"{i:064x}"[-64:] if n > 1 else "b" * 64, f"/tmp/{j}", {})
        ids.append(j)
    return ids


def test_twenty_jobs_four_workers_never_claimed_twice(pg, pg_dsn):
    ids = set(enqueue(pg, 20))
    claimed: list[tuple[str, str]] = []
    lock = threading.Lock()

    def worker(name: str) -> None:
        s = db.Store(db.connect(pg_dsn))
        while (row := s.claim(name)) is not None:
            with lock:
                claimed.append((row["id"], name))
        s.conn.close()

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    jobs = [j for j, _ in claimed]
    assert sorted(jobs) == sorted(ids)  # every job claimed exactly once
    assert len(jobs) == len(set(jobs))


def test_expired_lease_is_resumed_by_another_worker_with_its_state(pg):
    (j,) = enqueue(pg)
    first = pg.claim("w-crashes")
    pg.checkpoint(j, "w-crashes", {"stage_index": 1, "attempts": 3, "profile": {"x": 1}})
    # w-crashes dies: no more heartbeats. Another worker cannot take it while the lease holds.
    assert pg.claim("w-other") is None
    pg.conn.execute("UPDATE jobs SET lease_until = now() - interval '1 s' WHERE id = %s", (j,))
    second = pg.claim("w-other")
    assert first["id"] == second["id"] == j and second["claimed_from"] == "running"
    assert second["state"]["stage_index"] == 1 and second["state"]["attempts"] == 3
    with pytest.raises(db.LostLease):  # the crashed worker, if it comes back, is fenced off
        pg.heartbeat(j, "w-crashes")
    with pytest.raises(db.LostLease):
        pg.checkpoint(j, "w-crashes", {})


def test_transitions_need_the_expected_state(pg):
    (j,) = enqueue(pg)
    assert not pg.transition(j, "awaiting_approval", "approved")  # still queued
    assert pg.transition(j, "queued", "profile_review")
    assert not pg.transition(j, "queued", "profile_review")  # replay changes nothing


def test_duplicate_upload_points_to_the_existing_job(pg):
    (j,) = enqueue(pg)
    assert pg.enqueue(job_id(), "another:key", "b" * 64, "/tmp/x", {}) == (j, True)
    assert pg.enqueue(job_id(), f"src:{j}", "c" * 64, "/tmp/x", {}) == (j, True)


def test_ledger_is_append_only(pg):
    (j,) = enqueue(pg)
    for sql in ("UPDATE ledger SET event = 'x'", "DELETE FROM ledger", "TRUNCATE ledger"):
        with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
            pg.conn.execute(sql)
    assert [e["event"] for e in pg.events(j)] == ["queued"]


def test_kill_switch_and_daily_tokens(pg):
    pg.set_kill_switch(True)
    assert pg.kill_switch()
    pg.set_kill_switch(False)
    (j,) = enqueue(pg)
    pg.add_tokens(j, 1000)
    pg.add_tokens(j, 500)
    assert pg.tokens_today() == 1500 and pg.get(j)["tokens"] == 1500


def test_approve_is_refused_unless_awaiting_approval(pg, tmp_path):
    (j,) = enqueue(pg)
    records = promote.PgRecords(pg.conn, tmp_path / "runs")
    pg.conn.execute(
        "UPDATE jobs SET record = %s WHERE id = %s",
        (psycopg.types.json.Jsonb({"sha256_test": "d" * 64}), j),
    )
    with pytest.raises(promote.TransitionRefused, match="not awaiting_approval"):
        promote.approve(records, j, "d" * 64)
    pg.conn.execute("UPDATE jobs SET status = 'awaiting_approval' WHERE id = %s", (j,))
    assert promote.approve(records, j, "d" * 64).startswith("approved")
    assert pg.get(j)["status"] == "approved"
    assert "nothing to do" in promote.approve(records, j, "d" * 64)  # replay


def test_db_refuses_a_skipped_transition(pg, tmp_path):
    # Even with a forged record, the UPDATE only moves from an allowed previous status.
    (j,) = enqueue(pg)
    records = promote.PgRecords(pg.conn, tmp_path / "runs")
    with pytest.raises(promote.TransitionRefused, match="cannot move to done"):
        records.save(j, {"status": "done"})
    assert pg.get(j)["status"] == "queued"


def test_advisory_lock_serialises_splunk_writes(pg, pg_dsn):
    other = db.Store(db.connect(pg_dsn))
    with pg.advisory(db.SPLUNK_WRITE_LOCK):
        got = other.conn.execute(
            "SELECT pg_try_advisory_lock(%s) AS ok", (db.SPLUNK_WRITE_LOCK,)
        ).fetchone()["ok"]
        assert got is False  # a second worker must wait
    other.conn.close()


def test_the_app_role_cannot_rewrite_or_unprotect_the_ledger(pg, pg_dsn):
    # appsec Phase 5 M5: the engine connects as parsewright_app, not the owner.
    from urllib.parse import urlsplit, urlunsplit

    db.set_app_password(pg.conn, "app-role-test-only")
    url = urlsplit(pg_dsn)
    host = url.hostname + (f":{url.port}" if url.port else "")
    app_dsn = urlunsplit(url._replace(netloc=f"parsewright_app:app-role-test-only@{host}"))
    app = db.Store(db.connect(app_dsn))
    (j,) = enqueue(app)  # what the engine needs works
    assert app.claim("w1")["id"] == j
    assert app.transition(j, "running", "stage_failed", worker="w1")
    for sql in (
        "UPDATE ledger SET event = 'x'",
        "DELETE FROM ledger",
        "TRUNCATE ledger",
        "ALTER TABLE ledger DISABLE TRIGGER ledger_no_update",
        "DROP TRIGGER ledger_no_update ON ledger",
        "DELETE FROM jobs",
        "COPY ledger TO PROGRAM 'id'",
    ):
        with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)):
            app.conn.execute(sql)
    app.conn.close()
