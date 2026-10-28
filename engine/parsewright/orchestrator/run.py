"""Orchestrator: Profile -> (auto-approved review) -> Index-time -> Extraction -> CIM mapping.

Agents propose, code acts, Splunk judges: only this module deploys and ingests, and only the
Validator's reports move the run forward. Index-time attempts each ingest under a new
sourcetype; the search-time stages reuse the indexed events and only reinstall the add-on.
State is in memory (PostgreSQL arrives in Phase 5).
"""

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from parsewright import cim_spec
from parsewright.agents import cim_mapper, extraction, index_time, profiler
from parsewright.agents.llm import BadOutput, LLMClient
from parsewright.agents.profiler import LogProfile
from parsewright.guardrails import search_time
from parsewright.guardrails.index_time import GuardrailBlock, gate
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


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if manifest["event_count"] != len(manifest["epochs"]):
        raise ValueError("manifest event_count does not match its epochs")
    return manifest


def _regressed(check, stage: str):
    check.name = f"regression {stage}: {check.name}"
    return check


class Run:
    def __init__(self, path, llm, splunk, index, packages_dir, out, max_attempts):
        self.path, self.llm, self.splunk, self.out = path, llm, splunk, out
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

    # --- shared ------------------------------------------------------------------------

    def tick(self) -> None:
        if time.monotonic() - self.started > WALL_CLOCK_S:
            raise BudgetExhausted("15-minute wall clock reached")
        self.attempts += 1

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
        self.version += 1
        pkg = package.build(self.packages_dir, self.app, f"0.0.{self.version}", confs)
        self.built.append(pkg.path)
        self.splunk.install(pkg)

    def propose(self, stage: str, make: Callable, check: Callable):
        """One proposal through the gate, or (None, None), recorded in history, if refused."""
        proposal = None
        try:
            proposal = make()
            return proposal, check(proposal)
        except BadOutput as e:
            self.history[stage].append({"settings": {}, "outcome": f"bad output: {e}"})
            self.out(f"  bad output after retries: {e}")
        except GuardrailBlock as e:
            settings = proposal.model_dump() if proposal is not None else {}
            self.history[stage].append({"settings": settings, "outcome": f"blocked: {e}"})
            self.out(f"  guardrail block: {e}")
        return None, None

    # --- stages ------------------------------------------------------------------------

    def index_stage(self) -> bool:
        for attempt in range(1, self.max_attempts + 1):
            self.tick()
            st = test_sourcetype(self.prof.sourcetype, self.job, self.attempts)
            self.out(f"index-time attempt {attempt}: sourcetype {st}")
            _, settings = self.propose(
                "index-time",
                lambda: index_time.propose(
                    self.llm, self.prof, self.samples, self.history["index-time"]
                ),
                lambda p: gate(p.settings(), self.samples),
            )
            if settings is None:
                continue
            self.out(f"  proposal: {settings}")
            self.deploy(st, settings, {}, {})
            if self.splunk.count(self.index, st):  # never reuse a sourcetype (T4.5)
                raise RuntimeError(f"sourcetype {st} already has events in {self.index}")
            since = time.time() - 60  # sourcetype is unique per attempt: a wide window is safe
            self.splunk.ingest(self.index, st, self.text, ingest_source(self.path))
            report = index_validator.validate(
                self.splunk, self.index, st, self.manifest, since, self.app
            )
            print_report(report, self.out)
            if report.passed:
                self.st, self.confs["index"] = st, settings
                n = self.manifest["event_count"]
                self.out(f"index-time: PASS (event count {n}/{n}, attempt {attempt})")
                return True
            self.history["index-time"].append({"settings": settings, "outcome": report.evidence()})
        return False

    def extraction_stage(self) -> bool:
        for attempt in range(1, self.max_attempts + 1):
            self.tick()
            self.out(f"extraction attempt {attempt}")
            _, ext = self.propose(
                "extraction",
                lambda: extraction.propose(
                    self.llm, self.prof, self.samples, self.history["extraction"]
                ),
                lambda p: search_time.extraction(p, self.st, self.job, self.samples),
            )
            if ext is None:
                continue
            self.out(f"  proposal: {ext}")
            self.deploy(self.st, self.confs["index"], ext, {})
            report = self.check_search_time(lambda: self.extraction_report(skip=set()))
            if report.passed:
                self.confs["extraction"] = ext
                self.out(f"extraction: PASS (attempt {attempt})")
                return True
            self.history["extraction"].append({"settings": ext, "outcome": report.evidence()})
        return False

    def cim_stage(self) -> bool:
        models = [m for m in self.prof.cim_targets if m in cim_spec.ROOT] or list(cim_spec.ROOT)
        fields = self.field_values()
        for attempt in range(1, self.max_attempts + 1):
            self.tick()
            self.out(f"cim attempt {attempt}: models {', '.join(models)}")
            proposal, cim = self.propose(
                "cim",
                lambda models=models: cim_mapper.propose(
                    self.llm, self.prof, fields, models, self.history["cim"]
                ),
                lambda p: search_time.cim(p, self.st, self.job),
            )
            if cim is None:
                continue
            models = sorted({*models, *(e.model for e in proposal.eventtypes)})
            self.out(f"  proposal: {cim}")
            self.deploy(self.st, self.confs["index"], self.confs["extraction"], cim)
            targets = {
                k.split("-", 1)[1] for k in cim["props"] if k.startswith(("EVAL-", "FIELDALIAS-"))
            }
            report = self.check_search_time(lambda targets=targets: self.cim_report(targets))
            if report.passed:
                self.confs["cim"] = cim
                self.out(f"cim: PASS (attempt {attempt})")
                return True
            self.history["cim"].append({"settings": cim, "outcome": report.evidence()})
        return False

    # --- checks ------------------------------------------------------------------------

    def check_search_time(self, make_report: Callable[[], Report]) -> Report:
        """Validate; if it fails, reload search-time config once and validate again."""
        report = make_report()
        if not report.passed:
            self.splunk.reload_search_time()
            report = make_report()
        print_report(report, self.out)
        return report

    def extraction_report(self, skip: set[str]) -> Report:
        rows = self.splunk.field_rows(self.index, self.st)
        report = extraction_validator.validate(rows, self.manifest, self.prof, skip)
        regress = index_validator.regression(self.splunk, self.index, self.st, self.manifest)
        return Report(report.checks + [_regressed(c, "index-time") for c in regress.checks])

    def cim_report(self, targets: set[str]) -> Report:
        rows, children = {}, {}
        for model in cim_validator.expected_by_model(self.manifest):
            root = cim_spec.ROOT[model]
            rows[model] = self.splunk.datamodel_rows(model, root, self.index, self.st)
            children[model] = {
                ds: len(self.splunk.datamodel_rows(model, ds, self.index, self.st))
                for ds, _, _ in cim_spec.CHILDREN[model]
            }
        report, self.scores = cim_validator.validate(rows, children, self.manifest)
        earlier = self.extraction_report(skip=targets)
        return Report(report.checks + [_regressed(c, "extraction") for c in earlier.checks])

    def field_values(self) -> str:
        """Extracted fields with real values from the sample events, for the CIM mapper."""
        lines = []
        for r in self.splunk.field_summary(self.index, self.st, len(self.samples)):
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
    out: Callable[[str], None] = print,
    timezone: str | None = None,
    vendor: str | None = None,
    product: str | None = None,
    keep: bool = False,
    max_attempts: int = MAX_ATTEMPTS,
    stages: tuple[str, ...] = STAGES,
) -> RunResult:
    r = Run(path, llm, splunk, require_pw_index(test_index), packages_dir, out, max_attempts)
    out(f"job {r.job}: {path.name}, {r.manifest['event_count']} events in the manifest")
    r.prof = profiler.profile(llm, r.samples, timezone, vendor, product)
    out(
        f"profile: {r.prof.format}, {r.prof.vendor}/{r.prof.product}, sourcetype "
        f"{r.prof.sourcetype}, timestamp {r.prof.timestamp_example!r}, tz in timestamp: "
        f"{r.prof.timezone_in_timestamp}, fields {len(r.prof.fields)}, CIM {r.prof.cim_targets}"
    )
    out("profile review: auto-approved")
    r.app = test_app(r.prof.vendor, r.prof.product, r.job)
    result = RunResult(job=r.job, status="stage_failed", attempts=0, tokens=0, app=r.app)
    funcs = {"index-time": r.index_stage, "extraction": r.extraction_stage, "cim": r.cim_stage}
    try:
        i = 0
        while i < len(stages):
            if funcs[stages[i]]():
                i += 1
                continue
            out(f"{stages[i]}: FAIL after {max_attempts} attempts")
            if i > 0 and not result.backtracked:
                # One backtrack per run: the earlier stage may own the cause (design).
                result.backtracked = True
                last = r.history[stages[i]][-1]["outcome"] if r.history[stages[i]] else ""
                out(f"backtrack: re-running {stages[i - 1]} once with {stages[i]}'s evidence")
                r.history[stages[i - 1]].append(
                    {"settings": {}, "outcome": f"a later stage ({stages[i]}) failed:\n{last}"}
                )
                i -= 1
                continue
            result.failed_stage = stages[i]
            break
        else:
            result.status = "passed"
            out(
                f"holdout: learned from {len(r.samples)} lines, passed on the full file "
                f"({r.manifest['event_count']} events)"
            )
            for s in r.scores:
                out(s.line())
    except BudgetExhausted as e:
        result.failed_stage = "budget"
        out(f"budget: {e}")
    finally:
        result.tokens, result.attempts = llm.used, r.attempts
        result.sourcetype, result.history, result.scores = r.st, r.history, r.scores
        if not keep:
            splunk.uninstall(r.app)
            for p in r.built:
                p.unlink(missing_ok=True)
    out(f"tokens used: {result.tokens}")
    return result


def print_report(report: Report, out: Callable[[str], None]) -> None:
    for c in report.checks:
        out(
            f"  {'PASS' if c.passed else 'FAIL'} {c.name}: expected {c.expected}, actual {c.actual}"
        )
        for e in c.examples + c.operator_detail:
            out(f"    {e}")
