"""HTTP API for the UI: upload, runs, profile review, approve/reject, package download, and a
server-sent event stream of the ledger (design "Platform and UI").

Binds to localhost in the hackathon build (no login: residual risk R1). CORS allows only the
web origin, the Host header must be a known name (DNS rebinding, T8.5), and every response
carries security headers. All SQL goes through the parameterised Store.
"""

import asyncio
import json
import os
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from parsewright.api import intake
from parsewright.config import REPO, Settings, database_url, load_env_file
from parsewright.ledger import store as db
from parsewright.orchestrator import promote
from parsewright.orchestrator.worker import apply_corrections

JobId = Annotated[str, PathParam(pattern=r"^[a-z0-9]{4,16}$")]
SHA = re.compile(r"[0-9a-f]{64}")
CSRF_HEADER = "X-Parsewright"
MAX_BODY = 31 * 1024 * 1024  # 10 MB sample + 20 MB manifest + form overhead
MAX_STREAMS = 20
STREAMS = asyncio.Semaphore(MAX_STREAMS)
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def create_app(
    settings: Settings | None = None, dsn: str | None = None, migrate: bool = False
) -> FastAPI:
    if settings is None:
        load_env_file(REPO / ".env")
        settings = Settings.from_env()
    dsn = dsn or database_url()
    if migrate:  # only with the owner's credentials (tests, local); the engine runs as the app role
        with db.connect(dsn) as conn:
            db.migrate(conn)
    uploads = promote.runs_root(settings.runs_dir) / "uploads"
    uploads.mkdir(mode=0o700, exist_ok=True)

    app = FastAPI(title="Parsewright", docs_url=None, redoc_url=None, openapi_url=None)
    web_origin = os.environ.get("WEB_ORIGIN", "http://localhost:3000")
    app.add_middleware(BodyLimit, limit=MAX_BODY, paths=("/uploads",))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[web_origin],
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID", CSRF_HEADER],
    )
    hosts = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1,engine").split(",")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=[h.strip() for h in hosts])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        # CSRF (T8.3): a state-changing request needs a custom header, which a cross-site page
        # can only send after a CORS preflight that names this origin; a foreign Origin is
        # refused outright. A plain multipart form POST from another site is "simple" and
        # would otherwise go through without a preflight (appsec Phase 5 H1).
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if request.headers.get(CSRF_HEADER) != "1" or (origin and origin != web_origin):
                response = JSONResponse({"detail": "cross-site request refused"}, 403)
                response.headers.update(SECURITY_HEADERS)
                return response
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @contextmanager
    def connection() -> Iterator[db.Store]:
        conn = db.connect(dsn)
        try:
            yield db.Store(conn)
        finally:
            conn.close()

    def get_store() -> Iterator[db.Store]:
        with connection() as s:
            yield s

    StoreDep = Annotated[db.Store, Depends(get_store)]

    def job_or_404(store: db.Store, job: str) -> dict:
        row = store.get(job)
        if row is None:
            raise HTTPException(404, "no such run")
        return row

    @app.get("/health")
    def health(store: StoreDep) -> dict:
        store.conn.execute("SELECT 1")
        return {"status": "ok"}

    # --- intake ------------------------------------------------------------------------

    @app.post("/uploads", status_code=201)
    async def upload(
        store: StoreDep,
        file: Annotated[UploadFile, File()],
        manifest: Annotated[UploadFile | None, File()] = None,
        vendor: Annotated[str | None, Form(max_length=40)] = None,
        product: Annotated[str | None, Form(max_length=40)] = None,
        tz: Annotated[str | None, Form(max_length=64)] = None,
        auto_approve: Annotated[bool, Form()] = False,
    ) -> dict:
        try:
            name = intake.safe_name(file.filename or "")
            sample = intake.check(await file.read(intake.MAX_BYTES + 1))
            truth = await _manifest(manifest, sample)
            form = _form(vendor, product, tz, auto_approve) | {"file_name": name}
            estimate = intake.estimate_tokens(sample)
            if estimate > settings.run_token_ceiling:
                raise intake.UploadRefused(
                    f"estimated {estimate} tokens is over the per-run ceiling "
                    f"({settings.run_token_ceiling})"
                )
        except intake.UploadRefused as e:
            raise HTTPException(422, f"upload refused: {e}") from None
        # Fixed names in a fresh per-job folder (appsec M2): no user-derived path, no reuse.
        job = uuid.uuid4().hex[:8]
        folder = uploads / job
        folder.mkdir(mode=0o700)
        path = folder / "sample.log"
        _write_new(path, sample.text.encode("utf-8"))
        _write_new(folder / "sample.manifest.json", json.dumps(truth).encode("utf-8"))
        key = (
            f"{form['vendor']}:{form['product']}"
            if form.get("vendor") and form.get("product")
            else f"upload:{sample.sha256[:16]}"
        )
        job_id, duplicate = store.enqueue(job, key, sample.sha256, str(path), form)
        return {
            "job": job_id,
            "duplicate": duplicate,
            "events": sample.events,
            "estimated_tokens": estimate,
        }

    # --- runs --------------------------------------------------------------------------

    @app.get("/runs")
    def runs(store: StoreDep) -> list[dict]:
        return [_public(r) for r in store.jobs()]

    @app.get("/runs/{job}")
    def get_run(job: JobId, store: StoreDep) -> dict:
        return _public(job_or_404(store, job), detail=True)

    @app.get("/runs/{job}/events")
    def ledger(job: JobId, store: StoreDep, after: int = 0) -> list[dict]:
        job_or_404(store, job)
        return [_event(e) for e in store.events(job, after)]

    class Corrections(BaseModel):
        vendor: str | None = Field(None, max_length=40)
        product: str | None = Field(None, max_length=40)
        sourcetype: str | None = Field(None, max_length=80)
        tz: str | None = Field(None, max_length=64)

    @app.post("/runs/{job}/profile")
    def confirm_profile(job: JobId, body: Corrections, store: StoreDep) -> dict:
        row = job_or_404(store, job)
        if row["status"] != "profile_review":
            raise HTTPException(409, f"run is {row['status']}, not profile_review")
        state = dict(row["state"])
        try:
            state["profile"] = apply_corrections(state["profile"], body.model_dump())
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        state["profile_confirmed"] = True
        if not store.transition(job, "profile_review", "queued", state=state):
            raise HTTPException(409, "the run changed state; reload and try again")
        return {"job": job, "status": "queued"}

    class Approval(BaseModel):
        sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @app.post("/runs/{job}/approve")
    def approve(job: JobId, body: Approval, store: StoreDep) -> dict:
        job_or_404(store, job)
        records = promote.PgRecords(store.conn, settings.runs_dir)
        try:
            return {"job": job, "result": promote.approve(records, job, body.sha256)}
        except promote.TransitionRefused as e:
            raise HTTPException(409, str(e)) from None

    @app.post("/runs/{job}/reject")
    def reject(job: JobId, store: StoreDep) -> dict:
        if not store.transition(job, "awaiting_approval", "rejected"):
            raise HTTPException(409, "only a run awaiting approval can be rejected")
        return {"job": job, "status": "rejected"}

    @app.get("/runs/{job}/package")
    def download(job: JobId, store: StoreDep) -> FileResponse:
        row = job_or_404(store, job)
        folder = promote.runs_root(settings.runs_dir) / job
        name = "promoted.tgz" if row["status"] == "done" else "test.tgz"
        path = folder / name
        if (
            row["status"] not in ("awaiting_approval", "approved", "promoting", "done")
            or not path.is_file()
            or path.is_symlink()
        ):
            raise HTTPException(404, "no package for this run yet")
        app_name = (
            row["record"].get("app") if name == "promoted.tgz" else row["record"].get("test_app")
        )
        return FileResponse(path, media_type="application/gzip", filename=f"{app_name}.tgz")

    # --- live stream ---------------------------------------------------------------------

    @app.get("/runs/{job}/stream")
    async def stream(job: JobId, request: Request) -> StreamingResponse:
        with connection() as s:
            job_or_404(s, job)
        start = request.headers.get("last-event-id", "0")
        after = int(start) if start.isdigit() else 0
        if STREAMS.locked():
            raise HTTPException(503, "too many open event streams")
        return StreamingResponse(
            _capped(_sse(dsn, job, after, request)),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    # --- operator ------------------------------------------------------------------------

    class Kill(BaseModel):
        on: bool

    @app.get("/admin/status")
    def admin_status(store: StoreDep) -> dict:
        return {"kill_switch": store.kill_switch(), "tokens_today": store.tokens_today()}

    @app.post("/admin/kill")
    def kill(body: Kill, store: StoreDep) -> dict:
        store.set_kill_switch(body.on)
        return {"kill_switch": store.kill_switch()}

    return app


async def _capped(gen: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
    """Each stream holds a PostgreSQL connection: at most MAX_STREAMS at once (appsec L10)."""
    async with STREAMS:
        async for chunk in gen:
            yield chunk


class BodyLimit:
    """Refuse oversized request bodies before they are parsed or spooled to disk (appsec M4):
    Content-Length is required on the limited paths, and the bytes received are counted."""

    def __init__(self, app, limit: int, paths: tuple[str, ...]):
        self.app, self.limit, self.paths = app, limit, paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith(self.paths):
            return await self.app(scope, receive, send)
        length = dict(scope["headers"]).get(b"content-length", b"")
        if not length.isdigit() or int(length) > self.limit:
            response = JSONResponse({"detail": "request body too large or of unknown size"}, 413)
            return await response(scope, receive, send)
        seen = 0

        async def counted():
            nonlocal seen
            message = await receive()
            seen += len(message.get("body", b""))
            if seen > self.limit:
                raise HTTPException(413, "request body too large")
            return message

        return await self.app(scope, counted, send)


async def _sse(dsn: str, job: str, after: int, request: Request) -> AsyncIterator[bytes]:
    """Replay the job's ledger after `after`, then push each new row as it is inserted."""
    loop = asyncio.get_running_loop()
    conn = await loop.run_in_executor(None, db.connect, dsn)
    try:
        await loop.run_in_executor(None, conn.execute, "LISTEN ledger")
        store = db.Store(conn)
        while not await request.is_disconnected():
            rows = await loop.run_in_executor(None, store.events, job, after)
            for e in rows:
                after = e["id"]
                yield f"id: {e['id']}\nevent: ledger\ndata: {json.dumps(_event(e))}\n\n".encode()
            notes = await loop.run_in_executor(
                None, lambda: list(conn.notifies(timeout=1.0, stop_after=1))
            )
            if not notes and not rows:
                yield b": keep-alive\n\n"
    finally:
        conn.close()


async def _manifest(upload: UploadFile | None, sample: intake.Sample) -> dict:
    """The generator's truth manifest (this build validates against it): untrusted, checked."""
    if upload is None:
        raise intake.UploadRefused(
            "a truth manifest (.manifest.json) is required in this build; "
            "manifest-free validation is planned"
        )
    raw = await upload.read(20 * 1024 * 1024 + 1)
    try:
        truth = json.loads(raw)
    except (ValueError, RecursionError):
        raise intake.UploadRefused("the manifest is not JSON") from None
    epochs = truth.get("epochs") if isinstance(truth, dict) else None
    events = truth.get("events") if isinstance(truth, dict) else None
    if (
        not isinstance(epochs, list)
        or not all(isinstance(e, int) for e in epochs)
        or truth.get("event_count") != len(epochs)
        or not isinstance(events, list)
    ):
        raise intake.UploadRefused("the manifest needs event_count, epochs and events")
    if len(epochs) != sample.events:
        raise intake.UploadRefused("the manifest's event count does not match the file")
    # The manifest is the Validator's ground truth: every event must be described, matching
    # the epochs, or an empty or foreign events list could leave the CIM stage nothing to
    # check (appsec Phase 5 M1).
    if len(events) != len(epochs) or not all(_event_ok(e) for e in events):
        raise intake.UploadRefused("each manifest event needs epoch, category, fields and cim")
    if sorted(e["epoch"] for e in events) != sorted(epochs):
        raise intake.UploadRefused("the manifest's events do not match its epochs")
    return truth


def _event_ok(e: object) -> bool:
    def str_map(m: object) -> bool:
        return isinstance(m, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in m.items()
        )

    return (
        isinstance(e, dict)
        and isinstance(e.get("epoch"), int)
        and isinstance(e.get("category"), str)
        and str_map(e.get("fields"))
        and str_map(e.get("cim"))
    )


def _form(vendor, product, tz, auto_approve) -> dict:
    from parsewright.agents.profiler import clean_name
    from parsewright.guardrails.index_time import ALLOWED, GuardrailBlock

    form: dict = {"auto_approve": bool(auto_approve)}
    if vendor:
        form["vendor"] = clean_name(vendor)
    if product:
        form["product"] = clean_name(product)
    if tz:
        try:
            form["tz"] = ALLOWED["TZ"](tz)
        except GuardrailBlock as e:
            raise intake.UploadRefused(f"tz {e}") from None
    return form


def _write_new(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


def _event(e: dict) -> dict:
    return {"id": e["id"], "at": str(e["at"]), "event": e["event"], "data": e["data"]}


def _public(row: dict, detail: bool = False) -> dict:
    out = {
        "job": row["id"],
        "status": row["status"],
        "source_key": row["source_key"],
        "form": row["form"],
        "tokens": row.get("tokens", 0),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }
    if detail:
        state, record = row.get("state") or {}, row.get("record") or {}
        out["profile"] = state.get("profile")
        out["stage_index"] = state.get("stage_index")
        out["record"] = {
            k: v
            for k, v in record.items()
            if k
            in (
                "app",
                "test_app",
                "sourcetype",
                "sha256_test",
                "approved_sha256",
                "sha256_promoted",
                "smoke",
                "events",
                "report",
            )
        }
    return out
