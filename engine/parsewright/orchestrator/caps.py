"""Per-job and daily caps on test ingest bytes (design "Splunk safety": license use, T5.2)."""

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path


class IngestCapExceeded(RuntimeError):
    pass


class IngestCaps:
    def __init__(self, runs_dir: Path | None, job_mb: float, daily_mb: float):
        """runs_dir=None keeps the daily total in memory (tests, single runs)."""
        self.runs_dir, self.job_limit = runs_dir, int(job_mb * 1024 * 1024)
        self.daily_limit = int(daily_mb * 1024 * 1024)
        self.job_used = 0
        self.mem_daily = 0

    def reserve(self, nbytes: int) -> None:
        """Count nbytes against both caps before ingesting, or raise without counting."""
        if self.job_used + nbytes > self.job_limit:
            raise IngestCapExceeded(
                f"per-job ingest cap reached ({self.job_limit // 2**20} MB): "
                f"{self.job_used + nbytes} bytes requested"
            )
        if self.runs_dir is None:
            if self.mem_daily + nbytes > self.daily_limit:
                raise IngestCapExceeded(
                    f"daily ingest cap reached ({self.daily_limit // 2**20} MB)"
                )
            self.mem_daily += nbytes
            self.job_used += nbytes
            return
        self.runs_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        day = self.runs_dir / f"ingest-{datetime.now(UTC):%Y-%m-%d}.json"
        fd = os.open(
            self.runs_dir / ".ingest.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # parallel jobs (Phase 5) share the daily total
            used = json.loads(day.read_text())["bytes"] if day.exists() else 0
            if not isinstance(used, int) or used < 0:  # a tampered total fails closed
                raise IngestCapExceeded("daily ingest total is unreadable; refusing to ingest")
            if used + nbytes > self.daily_limit:
                raise IngestCapExceeded(
                    f"daily ingest cap reached ({self.daily_limit // 2**20} MB): {used} bytes used"
                )
            tmp = day.with_name(f".{day.name}.{os.getpid()}.tmp")
            tfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(tfd, "w") as f:
                f.write(json.dumps({"bytes": used + nbytes}))
            os.replace(tmp, day)
        self.job_used += nbytes
