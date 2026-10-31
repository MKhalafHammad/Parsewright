"""Orchestrator: Profile -> (auto-approved review) -> Index-time -> Extraction -> CIM mapping.

Agents propose, code acts, Splunk judges: only this module deploys and ingests, and only the
Validator's reports move the run forward. Index-time attempts each ingest under a new
sourcetype; the search-time stages reuse the indexed events and only reinstall the add-on.
State is in memory (PostgreSQL arrives in Phase 5).
"""

import dataclasses
import json
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from parsewright import cim_spec
from parsewright.agents import cim_mapper, extraction, index_time, profiler
from parsewright.agents.llm import BadOutput, LLMClient
from parsewright.agents.profiler import LogProfile
from parsewright.guardrails import conf_gate, search_time
from parsewright.guardrails.index_time import GuardrailBlock, gate
from parsewright.orchestrator import events, promote
from parsewright.orchestrator import report as report_mod
from parsewright.orchestrator.caps import IngestCapExceeded, IngestCaps
from parsewright.ta_builder import package
from parsewright.ta_builder.naming import require_pw_index, test_app, test_sourcetype
from parsewright.tools.splunk_client import SplunkClient, ingest_source
from parsewright.validator import cim as cim_validator
from parsewright.validator import extraction as extraction_validator
from parsewright.validator import index_time as index_validator
from parsewright.validator.index_time import Report

MAX_ATTEMPTS = 5
WALL_CLOCK_S = 15 * 60
SAMPLE_LINES = 200
STAGES = ("index-time", "extraction", "cim")
AGENT = {"index-time": "index_time", "extraction": "extraction", "cim": "cim_mapper"}
DEFAULT_FIELDS = {
    "host",
    "source",
    "sourcetype",
    "index",
    "linecount",
    "punct",
    "splunk_server",
    "timestamp",
    "eventtype",
    "tag",
    "t",
    "timeendpos",
    "timestartpos",
    "splunk_server_group",
}


class BudgetExhausted(Exception):
    pass


class RunAborted(Exception):
    """The worker lost its lease or the kill switch is on: stop without touching anything."""


@dataclass
class RunResult:
    job: str
    status: str  # "passed" | "stage_failed"
    attempts: int
    tokens: int
    app: str = ""
    sourcetype: str = ""
    failed_stage: str = ""
    backtracked: bool = False
    history: dict = field(default_factory=dict)
    scores: list = field(default_factory=list)


@dataclass
class SampleSet:
    """One sample file with its truth manifest and profile. A parser update validates several
    (the registry's old samples and the new ones) under one test sourcetype, told apart by
    their source."""

    label: str
    path: Path
    text: str
    manifest: dict
    profile: LogProfile
    source: str

    @property
    def lines(self) -> list[str]:
        return [line for line in self.text.splitlines() if line.strip()]


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if manifest["event_count"] != len(manifest["epochs"]):
        raise ValueError("manifest event_count does not match its epochs")
    return manifest


def _regressed(check, stage: str):
    check.name = f"regression {stage}: {check.name}"
    return check


class Run:
    def __init__(self, path, llm, splunk, index, packages_dir, out, max_attempts, caps):
        self.path, self.llm, self.splunk = path, llm, splunk
        self.out = events.sink(out)  # (line, meta); a plain line callable gets the line
        self.index, self.packages_dir, self.max_attempts = index, packages_dir, max_attempts
        self.text = path.read_text(encoding="utf-8")
        self.manifest = load_manifest(path)
        self.samples = [line for line in self.text.splitlines() if line.strip()][:SAMPLE_LINES]
        self.job = uuid.uuid4().hex[:8]
        self.started = time.monotonic()
        self.built: list[Path] = []
        self.version = 0
        self.attempts = 0
        self.history: dict[str, list[dict]] = {s: [] for s in STAGES}
        self.st = ""
        self.confs: dict[str, dict] = {"index": {}, "extraction": {}, "cim": {}}
        self.scores: list = []
        self.prof: LogProfile
        self.app = ""
        self.caps: IngestCaps = caps
        self.checked_transforms: set[str] = set()
        self.last_pkg: package.Package | None = None
        self.lock: Callable[[], AbstractContextManager] = nullcontext  # Splunk writes
        self.checkpoint: Callable[[dict], None] = lambda state: None
        self.abort: Callable[[], str | None] = lambda: None
        self.stage_index = 0
        # Where the run is, for the structured log events (metadata only, never a decision).
        self.ctx: dict = {"stage": None, "attempt": None, "visit": None}
        self.visits: dict[str, int] = {}  # entries into each stage loop

    def state(self) -> dict:
        """Everything needed to resume after a crash (design "Operation never stops")."""
        return {
            "profile": self.prof.model_dump(),
            "stage_index": self.stage_index,
            "attempts": self.attempts,  # persisted, so a resumed run never reuses a sourcetype
            "st": self.st,
            "confs": self.confs,
            "history": self.history,
            "version": self.version,
            "visits": self.visits,  # a resumed stage loop is a new visit in the log
        }

    def restore(self, state: dict) -> None:
        self.prof = LogProfile.model_validate(state["profile"])
        self.stage_index = state.get("stage_index", 0)
        self.attempts = state.get("attempts", 0)
        self.st = state.get("st", "")
        self.confs = state.get("confs", self.confs)
        self.history = {s: state.get("history", {}).get(s, []) for s in STAGES}
        self.version = state.get("version", 0)
        self.visits = dict(state.get("visits", {}))

    # --- structured log events -----------------------------------------------------------

    def emit(self, kind: str, actor: str, line: str, detail: dict | None = None, **where) -> None:
        """One log line with its metadata; `where` overrides the current stage/attempt/visit."""
        self.out(line, events.meta(kind, actor, detail=detail, **{**self.ctx, **where}))

    def emit_run(self, kind: str, actor: str, line: str, detail: dict | None = None) -> None:
        """A run-level event: no stage, attempt or visit."""
        self.emit(kind, actor, line, detail, stage=None, attempt=None, visit=None)

    def enter(self, stage: str) -> None:
        """Start of a stage loop. Only the build stages have visits (2 after the backtrack)."""
        visit = None
        if stage in STAGES:
            self.visits[stage] = visit = self.visits.get(stage, 0) + 1
        self.ctx = {"stage": stage, "attempt": None, "visit": visit}

    def add_evidence(self, to: str, settings, outcome: str, **where) -> None:
        """Record an outcome for the next attempt of stage `to`, and log what it will see."""
        self.history[to].append({"settings": settings, "outcome": outcome})
        self.emit(
            "evidence",
            "orchestrator",
            "  evidence for the next attempt",
            {"to": to, "text": outcome},
            **where,
        )

    def emit_proposal(self, stage: str, proposal, settings: dict, suffix: str = "") -> None:
        self.emit(
            "proposal",
            AGENT[stage],
            f"  proposal: {settings}{suffix}",
            {"settings": settings, "rationale": getattr(proposal, "rationale", None)},
        )

    def show_report(
        self, report: Report, sample_set: str | None = None, head=(), shown=None, **extra
    ) -> None:
        """One Validator event per report: the text lines as before, the checks as data."""
        lines = [*head, *report_lines(report if shown is None else shown)]
        if lines:
            self.emit(
                "check_pass" if report.passed else "check_fail",
                "validator",
                "\n".join(lines),
                {**report_detail(report, sample_set), **extra},
            )

    # --- shared ------------------------------------------------------------------------

    def tick(self) -> None:
        if reason := self.abort():
            raise RunAborted(reason)
        if time.monotonic() - self.started > WALL_CLOCK_S:
            raise BudgetExhausted("15-minute wall clock reached")
        self.attempts += 1
        self.checkpoint(self.state())  # before any Splunk write of this attempt

    def deploy(self, sourcetype: str, index_settings: dict, ext: dict, cim: dict) -> None:
        """Build and install the complete add-on: every stage's stanzas so far (Q6)."""
        props = {**index_settings, **ext.get("props", {}), **cim.get("props", {})}
        confs = {"props": {sourcetype: props}}
        for conf, stanzas in (
            ("transforms", ext.get("transforms")),
            ("eventtypes", cim.get("eventtypes")),
            ("tags", cim.get("tags")),
        ):
            if stanzas:
                confs[conf] = stanzas
        conf_gate.check(confs, self.job, sourcetype)  # final gate on exactly what is written
        new = sorted(set(confs.get("transforms", {})) - self.checked_transforms)
        if new and (taken := self.splunk.transforms_exist(new)):  # collision check (Q7)
            raise GuardrailBlock(f"transform names already exist in Splunk: {', '.join(taken)}")
        self.checked_transforms |= set(new)
        self.version += 1
        pkg = package.build(self.packages_dir, self.app, f"0.0.{self.version}", confs)
        self.built.append(pkg.path)
        with self.lock():  # one Splunk write at a time across all workers
            self.splunk.install(pkg)
        self.last_pkg = pkg
        version = f"0.0.{self.version}"
        self.emit(
            "deploy",
            "orchestrator",
            f"deploy: {self.app} {version}, sourcetype {sourcetype}",
            {"app": self.app, "version": version, "sourcetype": sourcetype, "sha256": pkg.sha256},
        )

    def propose(self, stage: str, make: Callable, check: Callable):
        """One proposal through the gate, or (None, None), recorded in history, if refused."""
        proposal = None
        try:
            proposal = make()
            return proposal, check(proposal)
        except BadOutput as e:
            self.emit(
                "guardrail_block",
                "gate",
                f"  bad output after retries: {e}",
                {"reason": str(e), "type": "bad_output"},
            )
            self.add_evidence(stage, {}, f"bad output: {e}")
        except GuardrailBlock as e:
            settings = proposal.model_dump(mode="json") if proposal is not None else {}
            self.emit(
                "guardrail_block",
                "gate",
                f"  guardrail block: {e}",
                {"reason": str(e), "settings": settings},
            )
            self.add_evidence(stage, settings, f"blocked: {e}")
        return None, None

    # --- stages ------------------------------------------------------------------------

    def index_stage(self) -> bool:
        self.enter("index-time")
        for attempt in range(1, self.max_attempts + 1):
            self.ctx["attempt"] = attempt
            self.tick()
            st = test_sourcetype(self.prof.sourcetype, self.job, self.attempts)
            self.emit(
                "start",
                "index_time",
                f"index-time attempt {attempt}: sourcetype {st}",
                {"max_attempts": self.max_attempts},
            )
            proposal, settings = self.propose(
                "index-time",
                lambda: index_time.propose(
                    self.llm, self.prof, self.samples, self.history["index-time"]
                ),
                lambda p: gate(p.settings(), self.samples),
            )
            if settings is None:
                continue
            self.emit_proposal("index-time", proposal, settings)
            self.deploy(st, settings, {}, {})
            if self.splunk.count(self.index, st):  # never reuse a sourcetype (T4.5)
                raise RuntimeError(f"sourcetype {st} already has events in {self.index}")
            since = time.time() - 60  # sourcetype is unique per attempt: a wide window is safe
            self.caps.reserve(len(self.text.encode("utf-8")))  # per-job and daily caps (T5.2)
            source = ingest_source(self.path)
            with self.lock():
                self.splunk.ingest(self.index, st, self.text, source)
            self.emit_ingest(st, [(source, self.text)])
            report = index_validator.validate(
                self.splunk, self.index, st, self.manifest, since, self.app, settings=settings
            )
            self.show_report(report)
            if report.passed:
                self.st, self.confs["index"] = st, settings
                n = self.manifest["event_count"]
                self.emit(
                    "check_pass",
                    "validator",
                    f"index-time: PASS (event count {n}/{n}, attempt {attempt})",
                )
                return True
            self.add_evidence("index-time", settings, report.evidence())
        return False

    def emit_ingest(self, st: str, sets: list[tuple[str, str]]) -> None:
        counts = [(src, len([ln for ln in text.splitlines() if ln.strip()])) for src, text in sets]
        total = sum(n for _, n in counts)
        more = f" from {len(sets)} sample sets" if len(sets) > 1 else ""
        self.emit(
            "ingest",
            "orchestrator",
            f"ingest: {total} events into {st}{more}",
            {"sourcetype": st, "sets": [{"source": src, "events": n} for src, n in counts]},
        )

    def extraction_stage(self) -> bool:
        self.enter("extraction")
        for attempt in range(1, self.max_attempts + 1):
            self.ctx["attempt"] = attempt
            self.tick()
            self.emit(
                "start",
                "extraction",
                f"extraction attempt {attempt}",
                {"max_attempts": self.max_attempts},
            )
            proposal, ext = self.propose(
                "extraction",
                lambda: extraction.propose(
                    self.llm, self.prof, self.samples, self.history["extraction"]
                ),
                lambda p: search_time.extraction(p, self.st, self.job, self.samples),
            )
            if ext is None:
                continue
            self.emit_proposal("extraction", proposal, ext)
            self.deploy(self.st, self.confs["index"], ext, {})
            report = self.check_search_time(lambda: self.extraction_report(skip=set()))
            if report.passed:
                self.confs["extraction"] = ext
                self.emit("check_pass", "validator", f"extraction: PASS (attempt {attempt})")
                return True
            self.add_evidence("extraction", ext, report.evidence())
        return False

    def cim_stage(self) -> bool:
        models = [m for m in self.prof.cim_targets if m in cim_spec.ROOT] or list(cim_spec.ROOT)
        fields = self.field_values()
        # Provenance uses the field names Splunk actually extracted, not the model's profile
        # (a profile could declare a field named "if" and make a constant look sourced).
        extracted = {line.split(" (", 1)[0] for line in fields.splitlines()}
        self.enter("cim")
        for attempt in range(1, self.max_attempts + 1):
            self.ctx["attempt"] = attempt
            self.tick()
            self.emit(
                "start",
                "cim_mapper",
                f"cim attempt {attempt}: models {', '.join(models)}",
                {"max_attempts": self.max_attempts},
            )
            proposal, cim = self.propose(
                "cim",
                lambda models=models: cim_mapper.propose(
                    self.llm, self.prof, fields, models, self.history["cim"]
                ),
                lambda p: search_time.cim(p, self.st, self.job, extracted),
            )
            if cim is None:
                continue
            models = sorted({*models, *(e.model for e in proposal.eventtypes)})
            self.emit_proposal("cim", proposal, cim)
            self.deploy(self.st, self.confs["index"], self.confs["extraction"], cim)
            targets = {
                k.split("-", 1)[1] for k in cim["props"] if k.startswith(("EVAL-", "FIELDALIAS-"))
            }
            report = self.check_search_time(lambda targets=targets: self.cim_report(targets))
            if report.passed:
                self.confs["cim"] = cim
                self.emit("check_pass", "validator", f"cim: PASS (attempt {attempt})")
                return True
            self.add_evidence("cim", cim, report.evidence())
        return False

    # --- checks ------------------------------------------------------------------------

    def check_search_time(self, make_report: Callable[[], Report]) -> Report:
        """Validate; if it fails, reload search-time config once and validate again."""
        report = make_report()
        if not report.passed:
            self.splunk.reload_search_time()
            report = make_report()
        self.show_report(report)
        return report

    def _set(self, s: SampleSet | None) -> tuple[dict, LogProfile, str | None]:
        return (s.manifest, s.profile, s.source) if s else (self.manifest, self.prof, None)

    def extraction_report(self, skip: set[str], s: SampleSet | None = None) -> Report:
        manifest, prof, source = self._set(s)
        rows = self.splunk.field_rows(self.index, self.st, source)
        report = extraction_validator.validate(rows, manifest, prof, skip)
        regress = index_validator.regression(self.splunk, self.index, self.st, manifest, source)
        return Report(report.checks + [_regressed(c, "index-time") for c in regress.checks])

    def cim_report(self, targets: set[str], s: SampleSet | None = None) -> Report:
        """Sets self.scores to this sample set's scores."""
        manifest, _, source = self._set(s)
        rows, children = {}, {}
        for model in cim_validator.expected_by_model(manifest):
            root = cim_spec.ROOT[model]
            rows[model] = self.splunk.datamodel_rows(model, root, self.index, self.st, source)
            children[model] = {
                ds: len(self.splunk.datamodel_rows(model, ds, self.index, self.st, source))
                for ds, _, _ in cim_spec.CHILDREN[model]
            }
        report, self.scores = cim_validator.validate(rows, children, manifest)
        earlier = self.extraction_report(skip=targets, s=s)
        return Report(report.checks + [_regressed(c, "extraction") for c in earlier.checks])

    def report(self, s: SampleSet | None = None) -> dict:
        """The approval report's data, from the passing attempt's indexed events."""
        manifest, prof, source = self._set(s)
        cim_props = {
            k: v
            for k, v in self.confs["cim"].get("props", {}).items()
            if k.startswith(("EVAL-", "FIELDALIAS-"))
        }
        extracted = [f.name for f in prof.fields] + [k.split("-", 1)[1] for k in cim_props]
        try:
            rows = self.splunk.report_rows(self.index, self.st, report_mod.MAX_EVENTS, source)
        except Exception as e:  # noqa: BLE001 - a report problem must not fail a passing run
            self.emit_run(
                "info",
                "orchestrator",
                f"report: could not read events ({type(e).__name__}); recorded without one",
            )
            return {}
        return report_mod.build(
            rows,
            list(dict.fromkeys(extracted)),
            cim_props,
            self.scores,
            self.last_pkg,
            len(self.samples),
            manifest["event_count"],
        )

    def field_values(self, source: str | None = None) -> str:
        """Extracted fields with real values from the sample events, for the CIM mapper."""
        lines = []
        for r in self.splunk.field_summary(self.index, self.st, len(self.samples), source):
            name = r.get("field", "")
            if name in DEFAULT_FIELDS or name.startswith(("date_", "_")):
                continue
            try:
                top = [v["value"] for v in json.loads(r.get("values") or "[]")][:5]
            except (ValueError, TypeError, KeyError):
                top = []
            lines.append(
                f"{name} (count {r.get('count')}, distinct {r.get('distinct_count')}): "
                + ", ".join(map(str, top))
            )
        return "\n".join(lines)


def run(
    path: Path,
    llm: LLMClient,
    splunk: SplunkClient,
    test_index: str,
    packages_dir: Path,
    out: Callable[..., None] = print,
    timezone: str | None = None,
    vendor: str | None = None,
    product: str | None = None,
    keep: bool = False,
    max_attempts: int = MAX_ATTEMPTS,
    stages: tuple[str, ...] = STAGES,
    runs_dir: Path | None = None,
    caps: IngestCaps | None = None,
    job: str | None = None,
    state: dict | None = None,
    checkpoint: Callable[[dict], None] | None = None,
    review: bool = False,
    lock: Callable[[], AbstractContextManager] | None = None,
    abort: Callable[[], str | None] | None = None,
    record: Callable[..., None] | None = None,
) -> RunResult:
    """review=True pauses after profiling (status "profile_review") until a human confirms;
    state resumes a checkpointed run; record replaces the file run record (database mode).
    out takes each log line; an events.Structured out also gets the line's metadata."""
    caps = caps or IngestCaps(runs_dir, job_mb=20, daily_mb=500)
    r = Run(path, llm, splunk, require_pw_index(test_index), packages_dir, out, max_attempts, caps)
    r.job = job or r.job
    r.lock, r.abort = lock or nullcontext, abort or (lambda: None)
    r.checkpoint = checkpoint or (lambda s: None)
    r.emit_run(
        "start",
        "orchestrator",
        f"job {r.job}: {path.name}, {r.manifest['event_count']} events in the manifest",
        start_detail("build", path, r.manifest, max_attempts, llm),
    )
    waiting = {"for": "profile_review"}
    if state and state.get("profile"):
        r.restore(state)
        if review:  # crashed between the profile checkpoint and the review pause (appsec L4)
            r.emit("human_wait", "human", "profile review: waiting for a human", waiting, **PROFILE)
            return RunResult(job=r.job, status="profile_review", attempts=0, tokens=llm.used)
        r.emit_run(
            "info",
            "orchestrator",
            f"resumed at stage {r.stage_index + 1}/{len(stages)} after {r.attempts} attempts",
        )
    else:
        r.prof = profiler.profile(llm, r.samples, timezone, vendor, product)
        r.emit(
            "proposal",
            "profiler",
            f"profile: {r.prof.format}, {r.prof.vendor}/{r.prof.product}, sourcetype "
            f"{r.prof.sourcetype}, timestamp {r.prof.timestamp_example!r}, tz in timestamp: "
            f"{r.prof.timezone_in_timestamp}, fields {len(r.prof.fields)}, "
            f"CIM {r.prof.cim_targets}",
            {"profile": r.prof.model_dump(mode="json")},
            **PROFILE,
        )
        r.checkpoint(r.state())
        if review:
            r.emit("human_wait", "human", "profile review: waiting for a human", waiting, **PROFILE)
            return RunResult(job=r.job, status="profile_review", attempts=0, tokens=llm.used)
        r.emit("info", "orchestrator", "profile review: auto-approved", **PROFILE)
    r.app = test_app(r.prof.vendor, r.prof.product, r.job)
    if state and state.get("profile"):
        with r.lock():  # a crashed attempt may have left this job's own test app installed
            splunk.uninstall(r.app)
    result = RunResult(job=r.job, status="stage_failed", attempts=0, tokens=0, app=r.app)
    funcs = {"index-time": r.index_stage, "extraction": r.extraction_stage, "cim": r.cim_stage}
    try:
        i = r.stage_index
        while i < len(stages):
            r.stage_index = i
            if funcs[stages[i]]():
                i += 1
                r.stage_index = i
                r.checkpoint(r.state())
                continue
            r.emit(
                "budget",
                "orchestrator",
                f"{stages[i]}: FAIL after {max_attempts} attempts",
                {"reason": "attempts"},
                attempt=None,
            )
            if i > 0 and not result.backtracked:
                # One backtrack per run: the earlier stage may own the cause (design).
                result.backtracked = True
                last = r.history[stages[i]][-1]["outcome"] if r.history[stages[i]] else ""
                back = {"stage": stages[i - 1], "attempt": None}
                back["visit"] = r.visits.get(stages[i - 1], 0) + 1  # the visit it starts
                r.emit(
                    "backtrack",
                    "orchestrator",
                    f"backtrack: re-running {stages[i - 1]} once with {stages[i]}'s evidence",
                    {"from": stages[i], "to": stages[i - 1], "because": last},
                    **back,
                )
                r.add_evidence(
                    stages[i - 1], {}, f"a later stage ({stages[i]}) failed:\n{last}", **back
                )
                i -= 1
                continue
            result.failed_stage = stages[i]
            break
        else:
            result.status = "passed"
            r.emit_run(
                "info",
                "validator",
                f"holdout: learned from {len(r.samples)} lines, passed on the full file "
                f"({r.manifest['event_count']} events)",
                {"learned_from": len(r.samples), "validated_on": r.manifest["event_count"]},
            )
            emit_scores(r)
            if record is not None and r.last_pkg is not None and stages == STAGES:
                record(
                    r.job,
                    r.last_pkg,
                    vendor=r.prof.vendor,
                    product=r.prof.product,
                    sourcetype=r.prof.sourcetype,
                    test_sourcetype=r.st,
                    sample=path,
                    report=r.report(),
                )
                r.emit_run(
                    "human_wait",
                    "human",
                    f"awaiting approval: sha256 {r.last_pkg.sha256}",
                    {"for": "approval", "sha256": r.last_pkg.sha256},
                )
            elif runs_dir is not None and r.last_pkg is not None and stages == STAGES:
                promote.record_passed_run(
                    runs_dir,
                    r.job,
                    r.last_pkg,
                    vendor=r.prof.vendor,
                    product=r.prof.product,
                    sourcetype=r.prof.sourcetype,
                    test_sourcetype=r.st,
                    sample=path,
                )
                r.emit_run(
                    "human_wait",
                    "human",
                    f"awaiting approval: parsewright approve {r.job} --sha256 {r.last_pkg.sha256}",
                    {"for": "approval", "sha256": r.last_pkg.sha256},
                )
    except (BudgetExhausted, IngestCapExceeded) as e:
        result.failed_stage = "budget"
        r.emit_run("budget", "orchestrator", f"budget: {e}", {"reason": str(e)})
    finally:
        result.tokens, result.attempts = llm.used, r.attempts
        result.sourcetype, result.history, result.scores = r.st, r.history, r.scores
        if not keep:
            splunk.uninstall(r.app)
            for p in r.built:
                p.unlink(missing_ok=True)
    r.emit_run("info", "orchestrator", f"tokens used: {result.tokens}", {"tokens": result.tokens})
    return result


PROFILE = {"stage": "profile", "attempt": None, "visit": None}


def start_detail(job_type: str, path: Path, manifest: dict, max_attempts: int, llm) -> dict:
    return {
        "job_type": job_type,
        "file": path.name,
        "events": manifest["event_count"],
        "max_attempts": max_attempts,
        "token_ceiling": getattr(llm, "ceiling", None),
        "wall_clock_s": WALL_CLOCK_S,
    }


def emit_scores(r: Run) -> None:
    for s in r.scores:
        r.emit_run("info", "validator", s.line(), {"score": dataclasses.asdict(s)})


def report_lines(report: Report) -> list[str]:
    """The text of a Validator report, as the CLI has always printed it."""
    lines = []
    for c in report.checks:
        lines.append(
            f"  {'PASS' if c.passed else 'FAIL'} {c.name}: expected {c.expected}, actual {c.actual}"
        )
        lines.extend(f"    {e}" for e in c.examples + c.operator_detail)
    return lines


def report_detail(report: Report, sample_set: str | None = None) -> dict:
    """The checks as data. operator_detail stays out (it may carry splunkd host paths)."""
    return {
        "sample_set": sample_set,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "expected": c.expected,
                "actual": c.actual,
                "examples": c.examples[:3],
            }
            for c in report.checks
        ],
    }


def print_report(report: Report, out: Callable[..., None], where: dict | None = None) -> None:
    """One Validator event for a report (outside a Run); `where` is its stage/attempt/visit."""
    lines = report_lines(report)
    if lines:
        kind = "check_pass" if report.passed else "check_fail"
        m = events.meta(kind, "validator", detail=report_detail(report), **(where or {}))
        events.sink(out)("\n".join(lines), m)
