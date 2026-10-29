"""Parser updates (design "Parser updates"): patch a promoted TA for a changed log format.

Diagnose (no AI) -> failing stages only, in patch mode -> Regression (old + new samples) ->
Approval -> Promote in place.

- The production TA, read from its hash-checked promoted package, is installed under this job's
  test identity. The new samples and every registered version's samples are ingested under one
  test sourcetype per attempt, told apart by source, and every check runs on every sample set:
  a patch that fixes the new format but breaks an old one is rejected with that evidence.
- If the production TA already passes on the new samples, the job ends at Diagnose having made
  no model call.
- Only TAs in the registry (built and promoted by Parsewright) can be updated. local/ is never
  written; the review flags the overrides in it that would hide the fix.
"""

import difflib
import hashlib
import os
import re
import time
from collections import Counter
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path

from parsewright.agents import cim_mapper, extraction, index_time
from parsewright.agents.llm import LLMClient
from parsewright.agents.profiler import FieldInfo, LogProfile
from parsewright.guardrails import search_time
from parsewright.guardrails.index_time import ALLOWED as INDEX_TIME
from parsewright.guardrails.index_time import GuardrailBlock, gate
from parsewright.orchestrator import promote
from parsewright.orchestrator.caps import IngestCapExceeded, IngestCaps
from parsewright.orchestrator.run import (
    MAX_ATTEMPTS,
    STAGES,
    BudgetExhausted,
    Run,
    RunResult,
    SampleSet,
    load_manifest,
    print_report,
)
from parsewright.ta_builder import package
from parsewright.ta_builder.conf_writer import write_conf
from parsewright.ta_builder.naming import require_job, require_pw_index, test_app, test_sourcetype
from parsewright.tools.splunk_client import PROPS_SYSTEM_DEFAULTS, SplunkClient
from parsewright.validator import index_time as index_validator
from parsewright.validator.index_time import Report

NEW_SOURCE = "parsewright_new"
OLD_SAMPLES_SHOWN = 20  # old-format lines each patch-mode agent sees
SEARCH_TIME_PREFIXES = ("EXTRACT-", "REPORT-")
CIM_PREFIXES = ("FIELDALIAS-", "EVAL-")


@dataclass
class Production:
    """A registered TA as it runs in production, with every version's samples."""

    app: str
    sourcetype: str
    vendor: str
    product: str
    owner_job: str
    version: str
    files: dict[str, str]  # its promoted package's files, as installed
    old: list[SampleSet]
    versions: tuple[str, ...] = ()  # every registered version

    @property
    def next_version(self) -> str:
        """A minor bump above the highest version ever registered, so an update after a
        rollback never reuses a version number."""
        return bump(max((*self.versions, self.version), key=_semver))

    @property
    def confs(self) -> dict:
        return promote.confs_from_files(self.files)


def load_production(store, runs_dir: Path, app: str) -> Production:
    """The registry's current version of `app`, refused unless its package matches its hash."""
    ta = store.ta(app)
    if ta is None:
        raise promote.TransitionRefused(
            f"{app} is not in the TA registry: only TAs promoted by Parsewright can be updated"
        )
    versions = store.ta_versions(app)
    current = next((v for v in versions if v["version"] == ta["current_version"]), None)
    if current is None:
        raise promote.TransitionRefused(f"{app}: the registry has no {ta['current_version']}")
    kept = promote.runs_root(runs_dir) / require_job(current["job_id"]) / "promoted.tgz"
    data = kept.read_bytes()
    if hashlib.sha256(data).hexdigest() != current["sha256"]:
        raise promote.TransitionRefused(
            f"{app} {ta['current_version']}: the kept package does not match the registry's hash"
        )
    old = []
    for i, v in enumerate(versions, 1):
        path, text = kept_samples(runs_dir, v)
        old.append(
            SampleSet(
                f"v{v['version']} samples",
                path,
                text,
                load_manifest(path),
                LogProfile.model_validate(v["profile"]),
                f"parsewright_old_{i}",
            )
        )
    return Production(
        app=ta["app"],
        sourcetype=ta["sourcetype"],
        vendor=ta["vendor"],
        product=ta["product"],
        owner_job=ta["owner_job"],
        version=ta["current_version"],
        files=promote.package_files(data, app),
        old=old,
        versions=tuple(v["version"] for v in versions),
    )


def _read_nofollow(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as f:
        return f.read()


def kept_samples(runs_dir: Path, version: dict) -> tuple[Path, str]:
    """A registered version's samples, only from the engine's private runs folder, never
    through a link, and only if they still have the hash recorded when the job was queued
    (manifest too, for jobs that recorded one): the regression set cannot be swapped."""
    root = promote.runs_root(runs_dir).resolve()
    path = Path(version["sample_path"])
    if path.resolve() != path or not path.is_relative_to(root):
        raise promote.TransitionRefused(
            f"v{version['version']} samples are outside the runs folder; refusing to use them"
        )
    data = _read_nofollow(path)
    if hashlib.sha256(data).hexdigest() != version["content_sha256"]:
        raise promote.TransitionRefused(f"v{version['version']} samples changed since intake")
    manifest = _read_nofollow(path.with_suffix(".manifest.json"))
    if version.get("manifest_sha256") and (
        hashlib.sha256(manifest).hexdigest() != version["manifest_sha256"]
    ):
        raise promote.TransitionRefused(f"v{version['version']} manifest changed since intake")
    return path, data.decode("utf-8")


def profile_for(base: LogProfile, manifest: dict) -> LogProfile:
    """The production profile with the new samples' field inventory, taken from their manifest's
    field names by code (no AI): a renamed field is checked under its new name."""
    n = max(manifest["event_count"], 1)
    counts = Counter(f for e in manifest["events"] for f in e["fields"])
    fields = [FieldInfo(name=f, coverage=round(c / n, 3)) for f, c in sorted(counts.items())]
    return base.model_copy(update={"fields": fields})


def _semver(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def bump(version: str) -> str:
    """A parser update is a minor version: 1.2.0 -> 1.3.0 (design)."""
    major, minor, _ = (int(x) for x in version.split("."))
    return f"{major}.{minor + 1}.0"


def split_stages(confs: dict, sourcetype: str, owner: str, job: str) -> dict[str, dict]:
    """Production confs as the three stages' settings, renamed to this job's test identity
    (transform and eventtype names parsewright_<owner>_ -> parsewright_<job>_)."""
    old, new = f"parsewright_{require_job(owner)}_", f"parsewright_{require_job(job)}_"

    def name(n: str) -> str:
        return new + n[len(old) :] if n.startswith(old) else n

    props = confs.get("props", {})
    if set(props) - {sourcetype}:
        raise promote.TransitionRefused("the production TA has props for another sourcetype")
    index, ext, cim = {}, {}, {}
    for key, value in props.get(sourcetype, {}).items():
        if key in INDEX_TIME:
            index[key] = value
        elif key == "KV_MODE" or key.startswith(SEARCH_TIME_PREFIXES):
            if key.startswith("REPORT-"):
                value = ", ".join(name(v.strip()) for v in value.split(","))
            ext[key] = value
        elif key.startswith(CIM_PREFIXES):
            cim[key] = value
        else:
            raise promote.TransitionRefused(f"the production TA has an unexpected key {key}")
    eventtypes = {name(e): dict(s) for e, s in confs.get("eventtypes", {}).items()}
    tags = {
        f"eventtype={name(t.removeprefix('eventtype='))}": dict(s)
        for t, s in confs.get("tags", {}).items()
    }
    return {
        "index": index,
        "extraction": {
            "props": ext,
            "transforms": {name(t): dict(s) for t, s in confs.get("transforms", {}).items()},
        },
        "cim": {"props": cim, "eventtypes": eventtypes, "tags": tags},
    }


def anchor(cim: dict, sourcetype: str) -> dict:
    """The CIM settings with every eventtype anchored on this attempt's sourcetype (the final
    gate still checks the exact anchor)."""
    eventtypes = {
        n: {**s, "search": re.sub(r"^sourcetype=\S+", f"sourcetype={sourcetype}", s["search"])}
        for n, s in cim.get("eventtypes", {}).items()
    }
    return {**cim, "eventtypes": eventtypes}


def cim_targets(cim: dict) -> set[str]:
    return {k.split("-", 1)[1] for k in cim.get("props", {}) if k.startswith(CIM_PREFIXES)}


def unified(old: dict[str, str], new: dict[str, str]) -> dict[str, str]:
    """Line-by-line diff per file, production -> update."""
    out = {}
    for rel in sorted(set(old) | set(new)):
        a, b = old.get(rel, ""), new.get(rel, "")
        if a != b:
            out[rel] = "".join(
                difflib.unified_diff(
                    a.splitlines(keepends=True),
                    b.splitlines(keepends=True),
                    f"production/{rel}",
                    f"update/{rel}",
                )
            )
    return out


def overrides(
    effective: dict[str, str], production: dict[str, str], update: dict[str, str]
) -> list[str]:
    """Keys the patch changes that Splunk takes from somewhere other than this TA's default/
    (an admin's local/ or another app): the fix will not take effect there (design)."""
    flags = []
    for key in sorted(set(production) | set(update)):
        if production.get(key) == update.get(key):
            continue
        applied = effective.get(key, "")
        expected = production.get(key, PROPS_SYSTEM_DEFAULTS.get(key, ""))
        if key not in production and applied in ("", expected):
            continue
        if key in production and applied == production[key]:
            continue
        change = f"set to {update[key]!r}" if key in update else "removed"
        flags.append(
            f"{key}: Splunk applies {applied!r} from local/ or another app, not this TA's "
            f"default/ ({production.get(key, 'unset')!r}). The patch has it {change}, which "
            "will not take effect until an admin updates or removes that override."
        )
    return flags


class UpdateRun(Run):
    def __init__(
        self,
        new: SampleSet,
        prod: Production,
        job: str,
        llm: LLMClient,
        splunk: SplunkClient,
        index: str,
        packages_dir: Path,
        out: Callable[[str], None],
        max_attempts: int,
        caps: IngestCaps,
    ):
        super().__init__(new.path, llm, splunk, index, packages_dir, out, max_attempts, caps)
        self.job, self.new, self.prod = job, new, prod
        self.prof = new.profile
        self.sets = [*prod.old, new]  # new last, so self.scores ends as the new samples' scores
        self.app = test_app(prod.vendor, prod.product, job)
        self.production = split_stages(prod.confs, prod.sourcetype, prod.owner_job, job)
        self.confs = {k: dict(v) for k, v in self.production.items()}
        self.drift: dict[str, str] = {}
        self.old_lines = [ln for s in prod.old for ln in s.lines[:OLD_SAMPLES_SHOWN]]

    # --- deploy, ingest, validate on every sample set -------------------------------------

    def deploy_all(self, st: str, **stage: dict) -> None:
        c = {**self.confs, **stage}
        self.deploy(st, c["index"], c["extraction"], anchor(c["cim"], st))

    def ingest_all(self, st: str) -> None:
        if self.splunk.count(self.index, st):  # never reuse a sourcetype (T4.5)
            raise RuntimeError(f"sourcetype {st} already has events in {self.index}")
        for s in self.sets:
            self.caps.reserve(len(s.text.encode("utf-8")))
            with self.lock():
                self.splunk.ingest(self.index, st, s.text, s.source)

    def index_reports(self, st: str, since: float, settings: dict) -> dict[str, Report]:
        return {
            s.label: index_validator.validate(
                self.splunk, self.index, st, s.manifest, since, self.app, s.source, settings
            )
            for s in self.sets
        }

    def search_reports(self, stage: str, cim: dict | None = None) -> dict[str, Report]:
        targets = cim_targets(cim if cim is not None else self.confs["cim"])

        def make() -> dict[str, Report]:
            if stage == "extraction":
                return {s.label: self.extraction_report(targets, s) for s in self.sets}
            return {s.label: self.cim_report(targets, s) for s in self.sets}

        reports = make()
        if not passed(reports):  # reload search-time config once, as a new build does
            self.splunk.reload_search_time()
            reports = make()
        return reports

    def show(self, reports: dict[str, Report]) -> None:
        for label, report in reports.items():
            self.out(f"  [{label}] {'PASS' if report.passed else 'FAIL'}")
            if not report.passed:
                print_report(Report([c for c in report.checks if not c.passed]), self.out)

    def evidence(self, reports: dict[str, Report]) -> str:
        parts = []
        for s in self.sets:
            report = reports[s.label]
            if report.passed:
                continue
            if s is self.new:
                parts.append(f"new samples:\n{report.evidence()}")
            else:
                parts.append(
                    f"REGRESSION, this change breaks the old format ({s.label}); both formats "
                    f"must parse:\n{report.evidence()}"
                )
        return "\n\n".join(parts)

    # --- the update flow -------------------------------------------------------------------

    def diagnose(self) -> int | None:
        """The production TA as it is, on every sample set, with no model call. Returns the
        first stage that fails on the new samples, or None if the TA already handles them."""
        self.tick()
        st = test_sourcetype(self.prod.sourcetype, self.job, self.attempts)
        self.out(f"diagnose: {self.prod.app} {self.prod.version} as installed, under {st} (no AI)")
        since = time.time() - 60
        self.deploy_all(st)
        self.ingest_all(st)
        self.st = st
        found = {"index-time": self.index_reports(st, since, self.confs["index"])}
        if passed(found["index-time"]):
            found["extraction"] = self.search_reports("extraction")
            found["cim"] = self.search_reports("cim")
        first = None
        for i, (stage, reports) in enumerate(found.items()):
            self.out(f"diagnose {stage}:")
            self.show(reports)
            old_failed = [s.label for s in self.prod.old if not reports[s.label].passed]
            if old_failed:
                raise promote.TransitionRefused(
                    f"{self.prod.app} {self.prod.version} fails its own registry samples "
                    f"({', '.join(old_failed)}) at {stage}; fix production before updating"
                )
            if not reports[self.new.label].passed:
                self.drift[stage] = reports[self.new.label].evidence()
                first = i if first is None else first
        if first is not None:
            self.out(f"drift report: {', '.join(self.drift)} fail on the new samples")
        return first

    def patch(self, first: int) -> str | None:
        """Patch mode from the first failing stage. A later stage that passes as it is is not
        patched (no model call). Returns the stage that ran out of attempts, or None."""
        for i, stage in enumerate(STAGES[first:], first):
            if i > first:
                reports = self.search_reports(stage)
                if passed(reports):
                    self.out(f"{stage}: passes as it is on every sample set, not patched")
                    continue
                self.drift[stage] = self.evidence(reports)
            if not self.patch_stage(stage):
                return stage
        return None

    def patch_context(self, stage: str) -> dict:
        """Production settings as the agent proposes them: eventtype names without the code-added
        parsewright_<job>_ prefix (shown prefixed, the model copied the prefix into its names)."""
        key = {"index-time": "index", "extraction": "extraction", "cim": "cim"}[stage]
        current = self.production[key]
        if key == "cim":
            prefix = f"parsewright_{self.job}_"
            current = {
                "props": current.get("props", {}),
                "eventtypes": {
                    n.removeprefix(prefix): s for n, s in current.get("eventtypes", {}).items()
                },
            }
        return {"current": current, "old_samples": self.old_lines}

    def keeps_eventtypes(self, cim: dict) -> dict:
        """Saved searches and dashboards use eventtype names: a patch may add eventtypes but
        never drop or rename a production one."""
        prefix = f"parsewright_{self.job}_"
        missing = sorted(set(self.production["cim"].get("eventtypes", {})) - set(cim["eventtypes"]))
        if missing:
            names = ", ".join(n.removeprefix(prefix) for n in missing)
            raise GuardrailBlock(
                f"keep the production eventtype names (searches use them): {names}"
            )
        return cim

    def patch_stage(self, stage: str) -> bool:
        history = self.history[stage]
        history.append(
            {
                "settings": "production (no attempt yet)",
                "outcome": f"drift report: the production settings on the new samples\n"
                f"{self.drift.get(stage, '')}",
            }
        )
        both = self.samples + self.old_lines  # gates check regexes against both formats
        for attempt in range(1, self.max_attempts + 1):
            self.tick()
            self.out(f"patch {stage} attempt {attempt}")
            patch = self.patch_context(stage)
            if stage == "index-time":
                _, settings = self.propose(
                    stage,
                    lambda patch=patch: index_time.propose(
                        self.llm, self.prof, self.samples, history, patch
                    ),
                    lambda p: gate(p.settings(), both),
                )
                if settings is None:
                    continue
                st = test_sourcetype(self.prod.sourcetype, self.job, self.attempts)
                self.out(f"  proposal: {settings} (sourcetype {st})")
                since = time.time() - 60
                self.deploy_all(st, index=settings)
                self.ingest_all(st)
                reports = self.index_reports(st, since, settings)
                change = {"index": settings}
            elif stage == "extraction":
                _, ext = self.propose(
                    stage,
                    lambda patch=patch: extraction.propose(
                        self.llm, self.prof, self.samples, history, patch
                    ),
                    lambda p: search_time.extraction(p, self.st, self.job, both),
                )
                if ext is None:
                    continue
                self.out(f"  proposal: {ext}")
                self.deploy_all(self.st, extraction=ext)
                reports, settings, change = self.search_reports(stage), ext, {"extraction": ext}
            else:
                fields = self.field_values(NEW_SOURCE)
                names = {ln.split(" (", 1)[0] for ln in fields.splitlines()}
                for s in self.prod.old:  # an alias may read a field only the old format has
                    old_fields = self.field_values(s.source).splitlines()
                    names |= {ln.split(" (", 1)[0] for ln in old_fields}
                models = self.prof.cim_targets
                _, cim = self.propose(
                    stage,
                    lambda f=fields, m=models, patch=patch: cim_mapper.propose(
                        self.llm, self.prof, f, m, history, patch
                    ),
                    lambda p, names=names: self.keeps_eventtypes(
                        search_time.cim(p, self.st, self.job, names)
                    ),
                )
                if cim is None:
                    continue
                self.out(f"  proposal: {cim}")
                self.deploy_all(self.st, cim=cim)
                reports, settings, change = self.search_reports(stage, cim), cim, {"cim": cim}
            self.show(reports)
            if passed(reports):
                if stage == "index-time":
                    self.st = st
                self.confs.update(change)
                self.out(f"{stage}: patched, PASS on the new and the old samples")
                return True
            history.append({"settings": settings, "outcome": self.evidence(reports)})
        return False

    def regression(self) -> dict[str, Report]:
        """The final package on every sample set: every stage's checks (CIM includes the
        extraction checks, which include the index-time data checks)."""
        self.out("regression: the final package on every registered version's samples and the new")
        reports = self.search_reports("cim")
        self.show(reports)
        return reports

    def update_review(self, record: dict) -> dict:
        """Diff against production, local/ overrides, notes, and one old event for the report."""
        version_to = self.prod.next_version
        files = promote.renamed_files(self.last_pkg.path.read_bytes(), record)
        files["default/app.conf"] = write_conf(package.app_conf(self.prod.app, version_to))
        prod_files = dict(self.prod.files)
        diff = unified(prod_files, files)
        before = self.prod.confs.get("props", {}).get(self.prod.sourcetype, {})
        after = promote.confs_from_files(files).get("props", {}).get(self.prod.sourcetype, {})
        try:
            effective = self.splunk.props_effective(self.prod.app, self.prod.sourcetype)
            flags = overrides(effective, before, after)
        except Exception as e:  # noqa: BLE001 - unknown is shown as unknown, never as "none"
            flags = [f"could not read the installed settings ({type(e).__name__}): check local/"]
        notes = ["Search-time changes apply to events already indexed as soon as it is promoted."]
        if any(before.get(k) != after.get(k) for k in set(before) | set(after) if k in INDEX_TIME):
            notes.append(
                "Index-time settings changed: they apply only to events indexed after promotion. "
                "Events already indexed keep their old line breaking and timestamps; re-ingest "
                "them from the source if needed."
            )
        old_report = self.report(self.prod.old[-1])
        return {
            "app": self.prod.app,
            "version_from": self.prod.version,
            "version_to": version_to,
            "patched": [s for s in STAGES if self.history[s]],
            "diff": diff,
            "overrides": flags,
            "notes": notes,
            "old_event": (old_report.get("events") or [None])[0],
            "rollback": f"parsewright rollback {self.prod.app} {self.prod.version}",
            "changed_keys": sorted(
                k for k in set(before) | set(after) if before.get(k) != after.get(k)
            ),
        }


def passed(reports: dict[str, Report]) -> bool:
    return all(r.passed for r in reports.values())


def run_update(
    path: Path,
    prod: Production,
    llm: LLMClient,
    splunk: SplunkClient,
    test_index: str,
    packages_dir: Path,
    job: str,
    out: Callable[[str], None] = print,
    caps: IngestCaps | None = None,
    max_attempts: int = MAX_ATTEMPTS,
    state: dict | None = None,
    checkpoint: Callable[[dict], None] | None = None,
    lock: Callable[[], AbstractContextManager] | None = None,
    abort: Callable[[], str | None] | None = None,
    record: Callable[..., None] | None = None,
) -> RunResult:
    """status: "no_change" (ended at Diagnose, no model call), "passed" (recorded awaiting
    approval) or "stage_failed". A resumed job starts again at Diagnose with fresh sourcetypes."""
    manifest = load_manifest(path)
    new = SampleSet(
        "new samples",
        path,
        path.read_text(encoding="utf-8"),
        manifest,
        profile_for(prod.old[-1].profile, manifest),
        NEW_SOURCE,
    )
    caps = caps or IngestCaps(None, job_mb=20, daily_mb=500)
    r = UpdateRun(
        new,
        prod,
        job,
        llm,
        splunk,
        require_pw_index(test_index),
        packages_dir,
        out,
        max_attempts,
        caps,
    )
    r.lock, r.abort = lock or nullcontext, abort or (lambda: None)
    r.checkpoint = checkpoint or (lambda s: None)
    r.attempts = (state or {}).get("attempts", 0)  # a resumed job never reuses a sourcetype
    out(
        f"update job {job}: {prod.app} {prod.version}, {manifest['event_count']} new events, "
        f"regression on {len(prod.old)} registered sample set(s)"
    )
    result = RunResult(job=job, status="stage_failed", attempts=0, tokens=0, app=r.app)
    with r.lock():  # a crashed attempt may have left this job's own test app installed
        splunk.uninstall(r.app)
    try:
        first = r.diagnose()
        if first is None:
            result.status = "no_change"
            out(f"diagnose: {prod.app} {prod.version} already parses the new samples; no change")
        elif failed := r.patch(first):
            result.failed_stage = failed
            out(f"{failed}: FAIL after {max_attempts} attempts")
        elif not passed(regression := r.regression()):
            result.failed_stage = "regression"
            out(f"regression: FAIL\n{r.evidence(regression)}")
        else:
            result.status = "passed"
            for s in r.scores:
                out(s.line())
            if record is not None and r.last_pkg is not None:
                info = {
                    "job": job,
                    "app": prod.app,
                    "test_app": r.app,
                    "sourcetype": prod.sourcetype,
                    "test_sourcetype": r.st,
                    "owner_job": prod.owner_job,
                }
                review = r.update_review(info)
                report = {**r.report(new), "update": review}
                record(
                    job,
                    r.last_pkg,
                    vendor=prod.vendor,
                    product=prod.product,
                    sourcetype=prod.sourcetype,
                    test_sourcetype=r.st,
                    sample=path,
                    report=report,
                    update={
                        "update_of": prod.app,
                        "owner_job": prod.owner_job,
                        "version_from": prod.version,
                        "version_to": review["version_to"],
                        "changed_keys": review["changed_keys"],
                    },
                )
                out(
                    f"awaiting approval: {prod.app} {prod.version} -> {review['version_to']}, "
                    f"sha256 {r.last_pkg.sha256}"
                )
    except (BudgetExhausted, IngestCapExceeded) as e:
        result.failed_stage = "budget"
        out(f"budget: {e}")
    finally:
        result.tokens, result.attempts = llm.used, r.attempts
        result.sourcetype, result.history, result.scores = r.st, r.history, r.scores
        splunk.uninstall(r.app)
        for p in r.built:
            p.unlink(missing_ok=True)
    out(f"tokens used: {result.tokens}")
    return result
