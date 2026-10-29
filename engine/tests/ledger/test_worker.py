"""Workers against real PostgreSQL with fake Splunk and a fake model: crash and resume."""

import dataclasses
import shutil

import pytest
from conftest import FIXTURES, PROFILE, FakeSplunk, fake_llm, proposal, settings, vpn_events

from parsewright.orchestrator import worker as worker_mod
from parsewright.orchestrator.run import RunAborted


@pytest.fixture
def env(pg, pg_dsn, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_dsn)
    work = tmp_path / "in"
    work.mkdir()
    for n in ("acme_vpn.json", "acme_vpn.manifest.json"):
        shutil.copy(FIXTURES / n, work / n)
    pkgs = tmp_path / "packages"
    pkgs.mkdir(mode=0o755)
    s = dataclasses.replace(settings(tmp_path), packages_dir=pkgs, runs_dir=tmp_path / "runs")
    return pg, s, work / "acme_vpn.json"


def make_worker(s, name, splunk, llm):
    w = worker_mod.Worker(s, name, out=lambda _: None, splunk=splunk, llm_factory=lambda: llm)
    w.stages = ("index-time",)
    return w


def test_crashed_worker_is_resumed_from_its_checkpoint(env, tmp_path, manifest):
    pg, s, sample = env
    pg.enqueue("res00001", "acme:vpn", "f" * 64, str(sample), {"auto_approve": True})
    wrong = vpn_events(manifest, 3600)
    right = vpn_events(manifest)

    # Worker 1 profiles, fails attempt 1, then "crashes" at the start of attempt 2.
    llm1 = fake_llm(tmp_path, [PROFILE, proposal(), proposal()])
    w1 = make_worker(s, "w1", FakeSplunk([wrong, right]), llm1)
    ticks = {"n": 0}
    real_build = w1.build

    def crash_on_second_tick(job, lost):
        original = worker_mod.run

        def run_and_crash(*a, **kw):
            inner = kw["abort"]

            def abort():
                ticks["n"] += 1
                return "simulated crash" if ticks["n"] == 2 else inner()

            kw["abort"] = abort
            return original(*a, **kw)

        worker_mod.run = run_and_crash
        try:
            return real_build(job, lost)
        finally:
            worker_mod.run = original

    w1.build = crash_on_second_tick
    assert w1.once()
    row = pg.get("res00001")
    assert row["status"] == "running" and row["state"]["attempts"] == 1  # checkpointed

    # Lease expires; worker 2 resumes: no new profile call, attempt numbering continues.
    pg.conn.execute("UPDATE jobs SET lease_until = now() - interval '1 s' WHERE id = 'res00001'")
    llm2 = fake_llm(tmp_path, [proposal()])  # only an index-time proposal, no profile
    splunk2 = FakeSplunk([right])
    w2 = make_worker(s, "w2", splunk2, llm2)
    assert w2.once()
    assert len(llm2._client.requests) == 1
    assert splunk2.ingested[0][1].endswith("_a2")  # never reuses _a1
    assert pg.get("res00001")["status"] == "done"
    events = [e["event"] for e in pg.events("res00001")]
    assert events.count("claimed") == 2


def test_kill_switch_stops_claims(env, tmp_path):
    pg, s, sample = env
    pg.enqueue("kill0001", "k:1", "9" * 64, str(sample), {"auto_approve": True})
    pg.set_kill_switch(True)
    w = make_worker(s, "w1", FakeSplunk([]), fake_llm(tmp_path, []))
    assert w.once() is False and pg.get("kill0001")["status"] == "queued"


def test_job_without_auto_approve_waits_for_profile_review(env, tmp_path):
    pg, s, sample = env
    pg.enqueue("rev00001", "r:1", "8" * 64, str(sample), {})
    w = make_worker(s, "w1", FakeSplunk([]), fake_llm(tmp_path, [PROFILE]))
    assert w.once()
    row = pg.get("rev00001")
    assert row["status"] == "profile_review" and row["worker_id"] is None
    assert row["state"]["profile"]["sourcetype"] == "acme:vpn"


def test_model_calls_stop_when_the_kill_switch_flips_mid_run(env, tmp_path):
    pg, s, _sample = env
    w = make_worker(s, "w1", FakeSplunk([]), fake_llm(tmp_path, []))
    pg.set_kill_switch(True)
    with pytest.raises(RunAborted, match="kill switch"), w.model_call_guard():
        pass
