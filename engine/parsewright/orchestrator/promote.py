"""Approval and promotion (design "Workflow integrity", "Test identity").

A passing run is recorded as awaiting approval with the SHA-256 of its exact test package.
Approval names that hash and is a one-way state change, so a replay is a no-op. Promotion reads
the stored package once, refuses unless those bytes have the approved hash, renames the test
identity back to the real names by code from those same bytes, refuses an existing TA name or
sourcetype, installs the real TA (Splunk itself refuses to overwrite an app), records both hashes
linked and runs a smoke test.

State lives in run records under PARSEWRIGHT_RUNS_DIR until PostgreSQL arrives (Phase 5). The
runs folder must be private to the engine user; every write is O_NOFOLLOW and atomic, and
transitions are checked and written under an exclusive lock, so the same rule holds as the
database's `UPDATE ... WHERE status = '<expected>'`. A process running as the engine user can
still forge a record (residual risk R9 until the database holds state).
"""

import fcntl
import hashlib
import io
import json
import os
import re
import tarfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from parsewright.guardrails import conf_gate
from parsewright.orchestrator.caps import IngestCaps
from parsewright.ta_builder import package
from parsewright.ta_builder.naming import (
    require_job,
    require_real_app,
    require_sourcetype,
    require_test_app,
    ta_name,
)
from parsewright.tools.splunk_client import SplunkClient

AWAITING, APPROVED, PROMOTING, DONE = "awaiting_approval", "approved", "promoting", "done"
FAILED, SMOKE_FAILED = "promotion_failed", "smoke_failed"
SMOKE_LINES = 20


class TransitionRefused(RuntimeError):
    pass


def runs_root(runs_dir: Path) -> Path:
    """The runs folder: created private if missing, then held to the packages-folder rules."""
    runs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return package.packages_dir(runs_dir.resolve())


# Each status may only be reached from these (database mode enforces it in the UPDATE).
PREVIOUS = {
    AWAITING: ("running",),
    APPROVED: (AWAITING,),
    PROMOTING: (APPROVED, PROMOTING),
    DONE: (PROMOTING,),
    SMOKE_FAILED: (PROMOTING,),
    FAILED: (PROMOTING,),
}


class PgRecords:
    """Run records in PostgreSQL (jobs.status + jobs.record); artifacts stay in the runs folder.

    Every save is UPDATE ... WHERE status = <an allowed previous status> with the row count
    checked, inside a SELECT ... FOR UPDATE transaction: the database enforces the transitions.
    """

    def __init__(self, conn, runs_dir: Path, worker: str | None = None):
        self.conn, self.runs_dir, self.worker = conn, runs_dir, worker
        self._tx: list = []

    def dir(self, job: str) -> Path:
        d = runs_root(self.runs_dir) / require_job(job)
        d.mkdir(mode=0o700, exist_ok=True)
        return d

    def load(self, job: str) -> dict:
        row = self.conn.execute("SELECT status, record FROM jobs WHERE id = %s", (job,)).fetchone()
        if row is None:
            raise TransitionRefused(f"no job {job}")
        return {**row["record"], "status": row["status"]}

    def save(self, job: str, record: dict) -> None:
        from psycopg.types.json import Jsonb

        new = record["status"]
        allowed = [*PREVIOUS.get(new, ()), new]
        sql = (
            "UPDATE jobs SET record = %s, status = %s, updated_at = now()"
            " WHERE id = %s AND status = ANY(%s)"
        )
        params: list = [
            Jsonb({k: v for k, v in record.items() if k != "status"}),
            new,
            job,
            allowed,
        ]
        if new == AWAITING and self.worker:
            sql += " AND worker_id = %s"
            params.append(self.worker)
        if self.conn.execute(sql, params).rowcount != 1:
            raise TransitionRefused(f"job {job} cannot move to {new} from its current status")
        self.conn.execute(
            "INSERT INTO ledger (job_id, event, data) VALUES (%s, %s, %s)",
            (job, "record", Jsonb({"status": new})),
        )

    @contextmanager
    def locked(self, job: str) -> Iterator[None]:
        with self.conn.transaction():
            self.conn.execute("SELECT id FROM jobs WHERE id = %s FOR UPDATE", (job,))
            yield


def _dir(runs, job: str) -> Path:
    if isinstance(runs, PgRecords):
        return runs.dir(job)
    return runs_root(runs) / require_job(job)


def _write_nofollow(path: Path, data: bytes) -> None:
    """Write via a fresh temp file opened O_EXCL|O_NOFOLLOW, then rename over the target."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)  # atomic: a crash leaves the old or the new file, never half


def load(runs_dir, job: str) -> dict:
    if isinstance(runs_dir, PgRecords):
        return runs_dir.load(job)
    return json.loads((_dir(runs_dir, job) / "record.json").read_text(encoding="utf-8"))


def _save(runs_dir, job: str, record: dict) -> None:
    if isinstance(runs_dir, PgRecords):
        return runs_dir.save(job, record)
    body = json.dumps(record, indent=1, sort_keys=True).encode("utf-8")
    _write_nofollow(_dir(runs_dir, job) / "record.json", body)


@contextmanager
def _locked(runs_dir, job: str) -> Iterator[None]:
    if isinstance(runs_dir, PgRecords):
        with runs_dir.locked(job):
            yield
        return
    fd = os.open(_dir(runs_dir, job) / ".lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _event(record: dict, what: str, **detail) -> None:
    record.setdefault("events", []).append(
        {"at": datetime.now(UTC).isoformat(timespec="seconds"), "event": what, **detail}
    )


def _validated(record: dict) -> dict:
    """Re-check every name taken from a record before it reaches Splunk (records are files)."""
    require_real_app(record["app"])
    require_test_app(record["test_app"])
    require_sourcetype(record["sourcetype"])
    if record["app"] != ta_name(record["vendor"], record["product"]):
        raise TransitionRefused("record app name does not match its vendor and product")
    return record


def record_passed_run(
    runs_dir: Path,
    job: str,
    test_pkg: package.Package,
    *,
    vendor: str,
    product: str,
    sourcetype: str,
    test_sourcetype: str,
    sample: Path,
) -> dict:
    """Keep the exact passing test package and record the run as awaiting approval."""
    d = _dir(runs_dir, job)
    d.mkdir(mode=0o700, exist_ok=isinstance(runs_dir, PgRecords))
    data = test_pkg.path.read_bytes()
    if hashlib.sha256(data).hexdigest() != test_pkg.sha256:
        raise RuntimeError("kept test package does not match the validated one")
    _write_nofollow(d / "test.tgz", data)
    lines = [ln for ln in sample.read_text(encoding="utf-8").splitlines() if ln][:SMOKE_LINES]
    _write_nofollow(d / "smoke.log", ("\n".join(lines) + "\n").encode("utf-8"))
    record = {
        "job": job,
        "status": AWAITING,
        "vendor": vendor,
        "product": product,
        "sourcetype": sourcetype,
        "test_sourcetype": test_sourcetype,
        "test_app": test_pkg.app,
        "app": ta_name(vendor, product),
        "sha256_test": test_pkg.sha256,
    }
    _validated(record)
    _event(record, "validated", sha256=test_pkg.sha256)
    _save(runs_dir, job, record)
    return record


def approve(runs_dir: Path, job: str, sha256: str) -> str:
    """awaiting_approval -> approved for exactly this hash. A replay of the same approval is a
    no-op; anything else is refused."""
    with _locked(runs_dir, job):
        record = load(runs_dir, job)
        if record["status"] != AWAITING:
            if record.get("approved_sha256") == sha256:
                return f"already {record['status']}: nothing to do"
            raise TransitionRefused(f"run is {record['status']}, not {AWAITING}")
        if sha256 != record["sha256_test"]:
            raise TransitionRefused("that hash is not the validated package's hash")
        record["status"], record["approved_sha256"] = APPROVED, sha256
        _event(record, "approved", sha256=sha256)
        _save(runs_dir, job, record)
    return f"approved {sha256}"


def renamed_files(test_tgz: bytes, record: dict) -> dict[str, str]:
    """The approved package's files with the test identity replaced by the real names, by code.

    Takes the bytes that were hashed, never a second read of the file (appsec M1). The test
    names contain __test_<job>, so plain token replacement cannot hit anything else.
    """
    swap = [(record["test_app"], record["app"]), (record["test_sourcetype"], record["sourcetype"])]
    files = {}
    with tarfile.open(fileobj=io.BytesIO(test_tgz)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                raise ValueError(f"unexpected member {member.name} in the approved package")
            text = tar.extractfile(member).read().decode("utf-8")
            for old, new in swap:
                text = text.replace(old, new)
            files[member.name.split("/", 1)[1]] = text
    return files


def promote(
    runs_dir: Path,
    job: str,
    splunk: SplunkClient,
    packages_dir: Path,
    test_index: str,
    caps: IngestCaps | None = None,
    out: Callable[[str], None] = print,
    start: str = APPROVED,
) -> dict:
    """start=PROMOTING when a worker has already claimed the approved job (database mode)."""
    with _locked(runs_dir, job):
        record = load(runs_dir, job)
        if record["status"] != start:
            raise TransitionRefused(f"run is {record['status']}, not {start}")
        _validated(record)
        data = (_dir(runs_dir, job) / "test.tgz").read_bytes()  # the only read of the package
        actual = hashlib.sha256(data).hexdigest()
        if actual != record["approved_sha256"]:
            _event(record, "promotion_refused", reason="hash mismatch", sha256=actual)
            _save(runs_dir, job, record)
            raise TransitionRefused(
                "the package changed after approval (hash mismatch); re-validate and re-approve"
            )
        for app in (record["app"], record["test_app"]):
            if splunk.app_exists(app):
                raise TransitionRefused(
                    f"{app} is installed in Splunk; refusing to promote over it"
                )
        if splunk.props_exist(record["sourcetype"]):
            raise TransitionRefused(
                f"sourcetype {record['sourcetype']} already has settings in Splunk "
                "(a built-in or another app's); refusing to merge into it"
            )
        record["status"] = PROMOTING
        _event(record, "promoting")
        _save(runs_dir, job, record)

    try:
        confs = _confs_from_files(renamed_files(data, record))
        conf_gate.check(confs, job, record["sourcetype"])  # the renamed package, same final gate
        real = package.build_promoted(packages_dir, record["app"], "1.0.0", confs)
        splunk.install(real, promotion=True)  # update=False: Splunk refuses an existing app
        _write_nofollow(_dir(runs_dir, job) / "promoted.tgz", real.path.read_bytes())
        real.path.unlink(missing_ok=True)
    except Exception as e:
        _finish(runs_dir, job, FAILED, "promotion_failed", reason=type(e).__name__)
        raise
    out(f"installed {record['app']} (sha256 {real.sha256})")
    out(f"  derived from approved test package {record['approved_sha256']}")

    try:
        smoke = smoke_test(splunk, record, test_index, job, runs_dir, caps)
    except Exception as e:  # noqa: BLE001 - a smoke test that cannot run has not passed
        smoke = f"FAIL (could not run: {type(e).__name__})"
    out(f"smoke test: {smoke}")
    status = DONE if smoke.startswith("PASS") else SMOKE_FAILED
    return _finish(
        runs_dir,
        job,
        status,
        "promoted",
        sha256_promoted=real.sha256,
        smoke=smoke,
        linked_to=record["approved_sha256"],
    )


def _finish(runs_dir: Path, job: str, status: str, event: str, **detail) -> dict:
    with _locked(runs_dir, job):
        record = load(runs_dir, job)
        record["status"] = status
        record.update({k: v for k, v in detail.items() if k in ("sha256_promoted", "smoke")})
        _event(record, event, **detail)
        _save(runs_dir, job, record)
    return record


def _confs_from_files(files: dict[str, str]) -> dict[str, dict[str, dict[str, str]]]:
    """Parse the writer's own output back into stanzas (app.conf and metadata are rebuilt)."""
    confs: dict[str, dict[str, dict[str, str]]] = {}
    for rel, text in files.items():
        m = re.fullmatch(r"default/(props|transforms|eventtypes|tags)\.conf", rel)
        if not m:
            continue
        stanzas: dict[str, dict[str, str]] = {}
        current: dict[str, str] | None = None
        for line in text.splitlines():
            if line.startswith("[") and line.endswith("]"):
                current = stanzas.setdefault(line[1:-1], {})
            elif line and current is not None:
                key, _, value = line.partition(" =")
                current[key] = value.removeprefix(" ")
        confs[m.group(1)] = stanzas
    return confs


def smoke_test(
    splunk: SplunkClient,
    record: dict,
    test_index: str,
    job: str,
    runs_dir: Path,
    caps: IngestCaps | None,
) -> str:
    """Ingest the run's own sample lines (copied at record time) under the real sourcetype into
    the test index, and check they arrive as the same number of events."""
    body = (_dir(runs_dir, job) / "smoke.log").read_text(encoding="utf-8")
    want = len([ln for ln in body.splitlines() if ln])
    if caps is not None:
        caps.reserve(len(body.encode("utf-8")))
    source = f"parsewright_smoke_{job}"
    splunk.ingest(test_index, record["sourcetype"], body, source)
    end, n = time.monotonic() + 90, 0
    while time.monotonic() < end:
        time.sleep(3)
        n = splunk.count(test_index, record["sourcetype"], source)
        if n >= want:
            break
    return f"PASS ({n}/{want} events)" if n == want else f"FAIL ({n}/{want} events)"
