"""Phase 2 orchestrator: Profile -> (auto-approved review) -> Index-time, state in memory.

Agents propose, code acts, Splunk judges: only this module deploys and ingests, and only the
Validator's report moves the run forward.
"""

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from parsewright.agents import index_time, profiler
from parsewright.agents.llm import BadOutput, LLMClient
from parsewright.guardrails.index_time import GuardrailBlock, gate
from parsewright.ta_builder import package
from parsewright.ta_builder.naming import require_pw_index, test_app, test_sourcetype
from parsewright.tools.splunk_client import SplunkClient, ingest_source
from parsewright.validator.index_time import Report, validate

MAX_ATTEMPTS = 5
WALL_CLOCK_S = 15 * 60
SAMPLE_LINES = 200


@dataclass
class RunResult:
    job: str
    status: str  # "passed" | "stage_failed"
    attempts: int
    tokens: int
    app: str = ""
    sourcetype: str = ""
    history: list[dict] = field(default_factory=list)


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    if manifest["event_count"] != len(manifest["epochs"]):
        raise ValueError("manifest event_count does not match its epochs")
    return manifest


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
) -> RunResult:
    started = time.monotonic()
    index = require_pw_index(test_index)
    text = path.read_text(encoding="utf-8")
    manifest = load_manifest(path)
    samples = [line for line in text.splitlines() if line.strip()][:SAMPLE_LINES]
    job = uuid.uuid4().hex[:8]

    out(f"job {job}: {path.name}, {manifest['event_count']} events in the manifest")
    prof = profiler.profile(llm, samples, timezone, vendor, product)
    out(
        f"profile: {prof.format}, {prof.vendor}/{prof.product}, sourcetype {prof.sourcetype}, "
        f"timestamp {prof.timestamp_example!r}, tz in timestamp: {prof.timezone_in_timestamp}"
    )
    out("profile review: auto-approved")

    app = test_app(prof.vendor, prof.product, job)
    result = RunResult(job=job, status="stage_failed", attempts=0, tokens=0, app=app)
    built: list[Path] = []
    try:
        for attempt in range(1, max_attempts + 1):
            if time.monotonic() - started > WALL_CLOCK_S:
                out("budget: 15-minute wall clock reached")
                break
            result.attempts = attempt
            st = test_sourcetype(prof.sourcetype, job, attempt)
            out(f"index-time attempt {attempt}: sourcetype {st}")
            try:
                proposal = index_time.propose(llm, prof, samples, result.history)
                settings = gate(proposal.settings(), samples)
            except BadOutput as e:
                result.history.append({"settings": {}, "outcome": f"bad output: {e}"})
                out(f"  bad output after retries: {e}")
                continue
            except GuardrailBlock as e:
                result.history.append({"settings": proposal.settings(), "outcome": f"blocked: {e}"})
                out(f"  guardrail block: {e}")
                continue
            out(f"  proposal: {settings}")

            pkg = package.build(packages_dir, app, f"0.0.{attempt}", {"props": {st: settings}})
            built.append(pkg.path)
            splunk.install(pkg)
            if splunk.count(index, st):  # never reuse a sourcetype with leftover events (T4.5)
                raise RuntimeError(f"sourcetype {st} already has events in {index}")
            since = time.time() - 60  # sourcetype is unique per attempt, so a wide window is safe
            splunk.ingest(index, st, text, ingest_source(path))
            report = validate(splunk, index, st, manifest, since, app)
            print_report(report, out)
            if report.passed:
                result.status, result.sourcetype = "passed", st
                out(
                    f"index-time: PASS (event count {manifest['event_count']}/"
                    f"{manifest['event_count']}, attempt {attempt})"
                )
                break
            result.history.append({"settings": settings, "outcome": report.evidence()})
        else:
            out(f"index-time: FAIL after {max_attempts} attempts")
    finally:
        result.tokens = llm.used
        if not keep:
            splunk.uninstall(app)
            for p in built:
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
