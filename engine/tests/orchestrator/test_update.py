"""Parser updates (Phase 7): Diagnose, patch mode, regression on old and new samples, in-place
promotion and rollback. Splunk and the model are faked; the Validator's verdicts are scripted,
and the real final gate checks every package that would be installed."""

import contextlib
import dataclasses
import hashlib
import inspect
import io
import json
import re
import shutil
import tarfile

import pytest
from conftest import FIXTURES, FakeSplunk, fake_llm

from parsewright.agents.profiler import LogProfile
from parsewright.guardrails import conf_gate
from parsewright.guardrails.index_time import GuardrailBlock
from parsewright.orchestrator import promote, update
from parsewright.orchestrator.run import SampleSet, load_manifest
from parsewright.orchestrator.update import (
    Production,
    UpdateRun,
    anchor,
    bump,
    overrides,
    profile_for,
    run_update,
    split_stages,
)
from parsewright.ta_builder import package
from parsewright.tools import splunk_client
from parsewright.tools.splunk_client import SplunkClient, SplunkError
from parsewright.validator.index_time import Check, Report

OWNER, JOB = "own00001", "upd00001"
APP, ST = "TA-parsewright-acme-firewall", "acme:fw"
PROD_PROPS = {
    "SHOULD_LINEMERGE": "false",
    "LINE_BREAKER": "([\\r\\n]+)",
    "TIME_PREFIX": "ts=",
    "TIME_FORMAT": "%s%3N",
    "MAX_TIMESTAMP_LOOKAHEAD": "13",
    "KV_MODE": "auto",
    "FIELDALIAS-dest": "dst AS dest",
}
PROD_CONFS = {
    "props": {ST: PROD_PROPS},
    "eventtypes": {f"parsewright_{OWNER}_traffic": {"search": f"sourcetype={ST}"}},
    "tags": {
        f"eventtype=parsewright_{OWNER}_traffic": {"network": "enabled", "communicate": "enabled"}
    },
}
FW_PROFILE = {
    "format": "kv",
    "multiline": False,
    "timestamp_example": "1792483219000",
    "timestamp_format_candidates": ["%s%3N"],
    "timezone_in_timestamp": True,
    "timezone_hint": None,
    "vendor": "acme",
    "product": "firewall",
    "sourcetype": ST,
    "event_categories": ["traffic"],
    "fields": [],
    "cim_targets": ["Network_Traffic"],
}
OLD, NEW = "v1.0.0 samples", "new samples"


def index_proposal() -> dict:
    """The minimal patch for two timestamp formats: drop TIME_FORMAT, keep the pin."""
    return {
        "should_linemerge": False,
        "line_breaker": "([\\r\\n]+)",
        "time_prefix": "ts=",
        "time_format": None,
        "max_timestamp_lookahead": 30,
        "tz": None,
        "truncate": None,
        "rationale": "v1 epoch ms and v2 ISO 8601 coexist",
    }


def report(ok: bool) -> Report:
    return Report([Check("timestamps", ok, "exact", "exact" if ok else "off by 3600 s")])


def verdicts(**labels: bool) -> dict[str, Report]:
    return {OLD if k == "old" else NEW: report(v) for k, v in labels.items()}


class UpdateSplunk(FakeSplunk):
    def __init__(self, effective=None):
        super().__init__([])
        self.effective = effective or {}
        self.updated: list = []

    def ingest(self, index, sourcetype, body, source):
        self.ingested.append((index, sourcetype, source))
        self.data.setdefault(sourcetype, []).extend((0, ln) for ln in body.splitlines() if ln)

    def props_effective(self, app, sourcetype):
        return self.effective

    def reload_search_time(self):
        pass

    def update_app(self, pkg, expected_version):
        self.updated.append((pkg, expected_version))


@pytest.fixture
def pkgs(tmp_path):
    d = tmp_path / "packages"
    d.mkdir(mode=0o755)
    return d


def sample(tmp_path, name: str):
    for suffix in (".log", ".manifest.json"):
        shutil.copy(FIXTURES / f"{name}{suffix}", tmp_path / f"{name}{suffix}")
    return tmp_path / f"{name}.log"


@pytest.fixture
def prod(tmp_path, pkgs) -> Production:
    built = package.build_promoted(pkgs, APP, "1.0.0", PROD_CONFS)
    files = promote.package_files(built.path.read_bytes(), APP)
    built.path.unlink()
    path = sample(tmp_path, "acme_fw")
    manifest = load_manifest(path)
    old = SampleSet(
        OLD,
        path,
        path.read_text(),
        manifest,
        profile_for(LogProfile(**FW_PROFILE), manifest),
        "parsewright_old_1",
    )
    return Production(APP, ST, "acme", "firewall", OWNER, "1.0.0", files, [old])


def scripted(monkeypatch, index: list, search: dict[str, list]):
    """Replace the Validator's verdicts; everything else (gate, deploy, ingest) runs for real."""
    monkeypatch.setattr(UpdateRun, "index_reports", lambda self, st, since, settings: index.pop(0))
    monkeypatch.setattr(
        UpdateRun, "search_reports", lambda self, stage, cim=None: search[stage].pop(0)
    )


def go(tmp_path, pkgs, prod, splunk, replies, **kw):
    lines: list[str] = []
    llm = fake_llm(tmp_path, replies)
    recorded: dict = {}
    result = run_update(
        sample(tmp_path, "acme_fw_v2"),
        prod,
        llm,
        splunk,
        "pw_test",
        pkgs,
        JOB,
        out=lines.append,
        record=lambda j, pkg, **k: recorded.update(job=j, pkg=pkg, **k),
        **kw,
    )
    return result, "\n".join(lines), llm, recorded


# --- the update flow ---------------------------------------------------------------------------


def test_new_samples_that_pass_as_is_end_at_diagnose_with_zero_tokens(
    tmp_path, pkgs, prod, monkeypatch
):
    scripted(
        monkeypatch,
        [verdicts(old=True, new=True)],
        {"extraction": [verdicts(old=True, new=True)], "cim": [verdicts(old=True, new=True)]},
    )
    splunk = UpdateSplunk()
    result, log, llm, recorded = go(tmp_path, pkgs, prod, splunk, [])
    assert result.status == "no_change" and result.tokens == 0
    assert llm._client.requests == [] and not recorded
    assert "already parses the new samples; no change" in log
    # both sample sets went into one test sourcetype, told apart by source
    assert {src for *_, src in splunk.ingested} == {"parsewright_old_1", "parsewright_new"}
    assert all(i.app.endswith(f"__test_{JOB}") for i in splunk.installed)
    assert splunk.uninstalled[-1] == f"{APP}__test_{JOB}" and not list(pkgs.iterdir())


def test_a_patch_that_breaks_the_old_format_is_rejected_with_evidence(
    tmp_path, pkgs, prod, monkeypatch
):
    scripted(
        monkeypatch,
        [
            verdicts(old=True, new=False),  # diagnose: the new timestamps fail
            verdicts(old=False, new=True),  # attempt 1 fixes v2 but breaks v1
            verdicts(old=True, new=True),  # attempt 2 parses both
        ],
        {
            "extraction": [verdicts(old=True, new=True)],
            "cim": [verdicts(old=True, new=True), verdicts(old=True, new=True)],
        },
    )
    splunk = UpdateSplunk()
    replies = [index_proposal() | {"time_format": "%Y-%m-%dT%H:%M:%S.%3NZ"}, index_proposal()]
    result, log, llm, recorded = go(tmp_path, pkgs, prod, splunk, replies)
    assert result.status == "passed", log
    second = llm._client.requests[1]["messages"]
    assert "Patch mode" in second[0]["content"]
    assert "REGRESSION, this change breaks the old format (v1.0.0 samples)" in second[1]["content"]
    assert "<old_format_samples>" in second[1]["content"]
    # only the failing stage's agent ran; later stages passed as they were
    assert len(llm._client.requests) == 2
    assert "extraction: passes as it is on every sample set, not patched" in log
    # every attempt had its own sourcetype
    assert sorted({st for _, st, _ in splunk.ingested}) == [
        f"{ST}__test_{JOB}_a1",
        f"{ST}__test_{JOB}_a2",
        f"{ST}__test_{JOB}_a3",
    ]
    assert recorded["update"]["version_to"] == "1.1.0"
    review = recorded["report"]["update"]
    assert "-TIME_FORMAT = %s%3N" in review["diff"]["default/props.conf"]
    assert "+version = 1.1.0" in review["diff"]["default/app.conf"]
    assert review["rollback"] == f"parsewright rollback {APP} 1.0.0"
    assert any("Index-time settings changed" in n for n in review["notes"])


def test_production_failing_its_own_samples_stops_before_any_model_call(
    tmp_path, pkgs, prod, monkeypatch
):
    scripted(monkeypatch, [verdicts(old=False, new=False)], {})
    splunk = UpdateSplunk()
    with pytest.raises(promote.TransitionRefused, match="fails its own registry samples"):
        go(tmp_path, pkgs, prod, splunk, [])
    assert splunk.uninstalled  # cleanup still ran


def test_patching_stops_at_the_attempt_budget(tmp_path, pkgs, prod, monkeypatch):
    scripted(monkeypatch, [verdicts(old=True, new=False)] + [verdicts(old=False, new=True)] * 2, {})
    replies = [index_proposal()] * 2
    result, *_ = go(tmp_path, pkgs, prod, UpdateSplunk(), replies, max_attempts=2)
    assert result.status == "stage_failed" and result.failed_stage == "index-time"


# --- naming, diff and overrides --------------------------------------------------------------


def test_production_settings_move_to_the_test_identity_and_back(prod, pkgs):
    stages = split_stages(prod.confs, ST, OWNER, JOB)
    st = f"{ST}__test_{JOB}_a2"
    cim = anchor(stages["cim"], st)
    assert list(cim["eventtypes"]) == [f"parsewright_{JOB}_traffic"]
    assert cim["eventtypes"][f"parsewright_{JOB}_traffic"]["search"] == f"sourcetype={st}"
    confs = {
        "props": {st: {**stages["index"], **stages["extraction"]["props"], **cim["props"]}},
        "eventtypes": cim["eventtypes"],
        "tags": cim["tags"],
    }
    conf_gate.check(confs, JOB, st)  # the test package passes the final gate under the job
    test_pkg = package.build(pkgs, f"{APP}__test_{JOB}", "0.0.3", confs)
    record = {
        "job": JOB,
        "owner_job": OWNER,
        "app": APP,
        "test_app": f"{APP}__test_{JOB}",
        "sourcetype": ST,
        "test_sourcetype": st,
    }
    back = promote.confs_from_files(promote.renamed_files(test_pkg.path.read_bytes(), record))
    conf_gate.check(back, OWNER, ST)  # and the promoted one under the TA's own names
    assert back["eventtypes"] == PROD_CONFS["eventtypes"] and back["props"][ST] == PROD_PROPS


def test_versions_bump_minor_above_every_registered_version(prod):
    assert bump("1.0.0") == "1.1.0" and bump("1.2.7") == "1.3.0"
    # rolled back to 1.0.0 after 1.1.0 and 1.10.0 existed: the next update is 1.11.0
    rolled_back = dataclasses.replace(prod, versions=("1.0.0", "1.1.0", "1.10.0"))
    assert rolled_back.next_version == "1.11.0"


def test_new_samples_are_checked_under_the_renamed_field():
    manifest = load_manifest(FIXTURES / "acme_fw_v2.log")
    names = {f.name for f in profile_for(LogProfile(**FW_PROFILE), manifest).fields}
    assert "src_ip" in names and "src" not in names


def test_local_overrides_that_hide_the_fix_are_flagged():
    before = {"TIME_FORMAT": "%s%3N", "KV_MODE": "auto"}
    after = {"KV_MODE": "auto", "FIELDALIAS-src": "src_ip AS src", "MAX_EVENTS": "256"}
    # the TA's own default/ is in effect: nothing to flag
    assert overrides({"TIME_FORMAT": "%s%3N", "MAX_EVENTS": "256"}, before, after) == []
    flags = overrides({"TIME_FORMAT": "%d/%m/%Y", "FIELDALIAS-src": "addr AS src"}, before, after)
    assert len(flags) == 2
    assert flags[0].startswith("FIELDALIAS-src: Splunk applies 'addr AS src'")
    assert "TIME_FORMAT: Splunk applies '%d/%m/%Y'" in flags[1] and "removed" in flags[1]


# --- installed-TA safety -------------------------------------------------------------------------


def _tgz(members: dict[str, bytes], link: str | None = None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        if link:
            info = tarfile.TarInfo(link)
            info.type, info.linkname = tarfile.SYMTYPE, "/etc"
            tar.addfile(info)
    return buf.getvalue()


@pytest.mark.parametrize(
    "members,link",
    [
        ({f"{APP}/../../etc/cron.d/x": b"x"}, None),  # path outside the TA
        ({"Splunk_SA_CIM/default/props.conf": b"x"}, None),  # another app
        ({f"{APP}/bin/run.py": b"x"}, None),  # not on the package allowlist
        ({f"{APP}/local/props.conf": b"x"}, None),  # local/ is never written
        ({}, f"{APP}/default"),  # a link
    ],
)
def test_a_kept_package_with_anything_outside_the_ta_is_refused(members, link):
    with pytest.raises(promote.TransitionRefused, match="unexpected member"):
        promote.package_files(_tgz(members, link), APP)


def test_nothing_in_the_engine_writes_local_or_conf_endpoints():
    """local/ belongs to admins: the only writes to Splunk are app installs and ingest."""
    source = inspect.getsource(splunk_client)
    posts = re.findall(r"\.post\(\s*f?\"([^\"]+)\"", source)
    assert set(posts) == {"apps/local", "receivers/simple"}
    for module in (promote, update):
        assert "configs/conf-" not in inspect.getsource(module)


class AppService:
    def __init__(self):
        self.posts: list = []

    def post(self, path, **kw):
        self.posts.append((path, kw))


@pytest.fixture
def client(tmp_path):
    from conftest import settings

    return SplunkClient(settings(tmp_path / "packages"), search=AppService(), deploy=AppService())


@pytest.mark.parametrize(
    "installed,match",
    [
        (None, "not installed"),
        ({"version": "1.1.0", "description": package.DESCRIPTION}, "registry's '1.0.0'"),
        ({"version": "1.0.0", "description": "Acme vendor TA"}, "not installed by Parsewright"),
    ],
)
def test_in_place_update_refuses_anything_but_the_expected_parsewright_ta(
    client, pkgs, monkeypatch, installed, match
):
    monkeypatch.setattr(client, "app_info", lambda app: installed)
    pkg = package.build_promoted(pkgs, APP, "1.1.0", PROD_CONFS)
    with pytest.raises(SplunkError, match=match):
        client.update_app(pkg, expected_version="1.0.0")
    assert client.deploy.posts == []


def test_in_place_update_replaces_only_with_update_true(client, pkgs, monkeypatch):
    monkeypatch.setattr(
        client, "app_info", lambda app: {"version": "1.0.0", "description": package.DESCRIPTION}
    )
    pkg = package.build_promoted(pkgs, APP, "1.1.0", PROD_CONFS)
    client.update_app(pkg, expected_version="1.0.0")
    assert client.deploy.posts == [
        ("apps/local", {"name": str(pkg.path.resolve()), "filename": True, "update": True})
    ]
    with pytest.raises(ValueError):  # a test app is never "updated in place"
        client.update_app(package.Package(pkg.path, f"{APP}__test_{JOB}", pkg.sha256), "1.0.0")


class RegistryStore:
    def __init__(self, versions):
        self.versions, self.current, self.events = versions, "1.1.0", []

    def ta(self, app):
        return {"app": APP, "sourcetype": ST, "owner_job": OWNER, "current_version": self.current}

    def ta_versions(self, app):
        return self.versions

    @contextlib.contextmanager
    def ta_lock(self, app):
        self.locked = True
        yield

    def set_current_version(self, app, previous, version, event):
        assert previous == self.current
        self.current = version
        self.events.append(event)


def _kept(tmp_path, pkgs, job: str, data: bytes) -> None:
    runs = tmp_path / "runs"
    (runs / job).mkdir(parents=True, mode=0o700)
    runs.chmod(0o700)
    (runs / job / "promoted.tgz").write_bytes(data)


def test_rollback_reinstalls_the_exact_version(tmp_path, pkgs):
    v1 = package.build_promoted(pkgs, APP, "1.0.0", PROD_CONFS)
    data = v1.path.read_bytes()
    v1.path.unlink()
    _kept(tmp_path, pkgs, OWNER, data)
    store = RegistryStore([{"version": "1.0.0", "job_id": OWNER, "sha256": v1.sha256}])
    splunk = UpdateSplunk()
    out = promote.rollback(store, tmp_path / "runs", APP, "1.0.0", splunk, pkgs, out=lambda _: None)
    assert out == "rolled back to 1.0.0" and store.current == "1.0.0" and store.locked
    ((installed, expected),) = splunk.updated
    assert installed.sha256 == v1.sha256 and expected == "1.1.0"
    assert not list(pkgs.iterdir())  # the rebuilt package is removed after install


def test_rollback_refuses_a_changed_package(tmp_path, pkgs):
    v1 = package.build_promoted(pkgs, APP, "1.0.0", PROD_CONFS)
    tampered = _tgz({f"{APP}/default/props.conf": b"[acme:fw]\nTRANSFORMS-x = drop\n"})
    v1.path.unlink()
    _kept(tmp_path, pkgs, OWNER, tampered)
    store = RegistryStore([{"version": "1.0.0", "job_id": OWNER, "sha256": v1.sha256}])
    splunk = UpdateSplunk()
    with pytest.raises(promote.TransitionRefused, match="does not match its hash"):
        promote.rollback(store, tmp_path / "runs", APP, "1.0.0", splunk, pkgs)
    assert splunk.updated == [] and store.current == "1.1.0"


# --- the registry (PostgreSQL) -------------------------------------------------------------------


def _done_job(pg, job: str, app: str = APP) -> None:
    pg.enqueue(job, f"k:{job}", hashlib.sha256(job.encode()).hexdigest(), "/x.log", {})
    record = {
        "job": job,
        "app": app,
        "sourcetype": ST,
        "vendor": "acme",
        "product": "firewall",
        "sha256_promoted": "a" * 64,
    }
    pg.conn.execute(
        "UPDATE jobs SET status = 'done', record = %s WHERE id = %s", (json.dumps(record), job)
    )


def test_registry_versions_are_append_only_and_updates_need_the_current_version(pg):
    import psycopg

    _done_job(pg, OWNER)
    _done_job(pg, JOB)
    pg.register_ta(
        {"job": OWNER, "app": APP, "sourcetype": ST, "vendor": "acme", "product": "firewall"},
        "1.0.0",
        "a" * 64,
    )
    pg.add_version(APP, "1.0.0", "1.1.0", JOB, "b" * 64)
    assert pg.ta(APP)["current_version"] == "1.1.0"
    with pytest.raises(RuntimeError, match=r"no longer at version 1\.0\.0"):
        pg.set_current_version(APP, "1.0.0", "1.2.0", "updated")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        pg.conn.execute("UPDATE ta_versions SET sha256 = %s", ("c" * 64,))
    assert [t["versions"] for t in pg.tas()] == [["1.0.0", "1.1.0"]]


def test_update_promotion_needs_the_registry_at_the_expected_version(pg, tmp_path):
    _done_job(pg, OWNER)
    records = promote.PgRecords(pg.conn, tmp_path)
    record = {"app": APP, "sourcetype": ST, "owner_job": OWNER, "version_from": "1.0.0"}
    with pytest.raises(promote.TransitionRefused, match="not in the TA registry"):
        promote._registry_allows_update(records, record)
    pg.register_ta(
        {"job": OWNER, "app": APP, "sourcetype": ST, "vendor": "acme", "product": "firewall"},
        "1.0.0",
        "a" * 64,
    )
    promote._registry_allows_update(records, record)  # allowed
    with pytest.raises(promote.TransitionRefused, match="re-run the update"):
        promote._registry_allows_update(records, record | {"version_from": "0.9.0"})
    with pytest.raises(promote.TransitionRefused, match="need the TA registry"):
        promote._registry_allows_update(tmp_path, record)


def test_migration_backfills_tas_promoted_before_the_registry(pg):
    from parsewright.ledger import store as db

    _done_job(pg, OWNER)
    for name in ("003_ta_registry.sql", "004_registry_grants.sql"):  # both idempotent
        pg.conn.execute((db.MIGRATIONS / name).read_text())  # the backfill finds the done job
    assert pg.ta(APP)["owner_job"] == OWNER
    assert [v["version"] for v in pg.ta_versions(APP)] == ["1.0.0"]


def test_a_cim_patch_may_add_but_never_drop_a_production_eventtype(tmp_path, pkgs, prod):
    """Adversarial: renaming an eventtype in production breaks every search that uses it."""
    r = UpdateRun(
        SampleSet(NEW, prod.old[0].path, "x", prod.old[0].manifest, prod.old[0].profile, "n"),
        prod,
        JOB,
        fake_llm(tmp_path, []),
        UpdateSplunk(),
        "pw_test",
        pkgs,
        print,
        5,
        None,
    )
    kept = f"parsewright_{JOB}_traffic"
    shown = r.patch_context("cim")["current"]["eventtypes"]
    assert list(shown) == ["traffic"]  # the agent sees the name it proposes, not the prefix
    r.keeps_eventtypes({"eventtypes": {kept: {}, f"parsewright_{JOB}_extra": {}}})
    with pytest.raises(GuardrailBlock, match=r"keep the production eventtype names.*traffic"):
        r.keeps_eventtypes({"eventtypes": {f"parsewright_{JOB}_network": {}}})


def _version(path, sample_text: str) -> dict:
    return {
        "version": "1.0.0",
        "sample_path": str(path),
        "content_sha256": hashlib.sha256(sample_text.encode()).hexdigest(),
        "manifest_sha256": None,
    }


def test_regression_samples_come_only_from_the_runs_folder_unchanged(tmp_path):
    """Adversarial (appsec Phase 7 M1): a swapped, linked or outside sample set is refused."""
    runs = tmp_path / "runs"
    folder = runs / "uploads" / OWNER
    folder.mkdir(parents=True, mode=0o700)
    runs.chmod(0o700)
    text = (FIXTURES / "acme_fw.log").read_text()
    (folder / "sample.log").write_text(text)
    shutil.copy(FIXTURES / "acme_fw.manifest.json", folder / "sample.manifest.json")
    _, got = update.kept_samples(runs, _version(folder / "sample.log", text))
    assert got == text
    outside = sample(tmp_path, "acme_fw")
    with pytest.raises(promote.TransitionRefused, match="outside the runs folder"):
        update.kept_samples(runs, _version(outside, text))
    link = folder / "linked.log"
    link.symlink_to(outside)
    with pytest.raises(promote.TransitionRefused, match="outside the runs folder"):
        update.kept_samples(runs, _version(link, text))
    (folder / "sample.log").write_text(text.replace("accept", "drop"))
    with pytest.raises(promote.TransitionRefused, match="changed since intake"):
        update.kept_samples(runs, _version(folder / "sample.log", text))


def test_promotions_and_rollbacks_of_one_ta_are_serialised(pg, pg_dsn):
    from parsewright.ledger import store as db

    other = db.connect(pg_dsn)
    try:
        with pg.ta_lock(APP):
            held = other.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s)) AS ok", (f"ta:{APP}",)
            ).fetchone()["ok"]
            assert held is False
    finally:
        other.close()


def test_a_fresh_build_of_a_registered_ta_is_refused(pg, tmp_path):
    """Adversarial (appsec Phase 7 M2): a new build must not install over the registry's TA."""
    _done_job(pg, OWNER)
    pg.register_ta(
        {"job": OWNER, "app": APP, "sourcetype": ST, "vendor": "acme", "product": "firewall"},
        "1.0.0",
        "a" * 64,
    )
    assert promote._registered(promote.PgRecords(pg.conn, tmp_path), APP)
    assert not promote._registered(tmp_path, APP)  # file mode: no registry


def test_a_changed_key_not_in_effect_after_install_is_caught():
    """appsec Phase 7 L3: a local/ value equal to the old default hides the fix from the review;
    reading the effective settings back after the install catches it."""

    class Effective:
        def __init__(self, values):
            self.values = values

        def props_effective(self, app, sourcetype):
            return self.values

    record = {"app": APP, "sourcetype": ST, "changed_keys": ["EVAL-src", "TIME_FORMAT"]}
    confs = {"props": {ST: {"EVAL-src": "coalesce(src_ip,src)"}}}
    applied = Effective({"EVAL-src": "coalesce(src_ip,src)"})
    assert promote._not_in_effect(applied, record, confs) == []
    kept_local = Effective({"EVAL-src": "coalesce(src_ip,src)", "TIME_FORMAT": "%s%3N"})
    assert promote._not_in_effect(kept_local, record, confs) == ["TIME_FORMAT"]


def test_the_app_role_can_only_move_a_tas_version(pg, pg_dsn):
    """appsec Phase 7 L4: the engine role cannot repoint a TA's owner job or sourcetype."""
    import psycopg

    _done_job(pg, OWNER)
    pg.register_ta(
        {"job": OWNER, "app": APP, "sourcetype": ST, "vendor": "acme", "product": "firewall"},
        "1.0.0",
        "a" * 64,
    )
    with psycopg.connect(pg_dsn, autocommit=True) as conn:
        conn.execute("SET ROLE parsewright_app")
        conn.execute("UPDATE tas SET current_version = '1.0.0', updated_at = now()")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE tas SET owner_job = 'evil0001'")
