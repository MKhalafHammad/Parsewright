import shutil

import pytest
from conftest import FIXTURES, PROFILE, FakeSplunk, collect_events, fake_llm, proposal, vpn_events

from parsewright.agents.llm import TokenCeilingExceeded
from parsewright.orchestrator.run import Run, run


@pytest.fixture
def sample(tmp_path):
    work = tmp_path / "in"
    work.mkdir()
    for name in ("acme_vpn.json", "acme_vpn.manifest.json"):
        shutil.copy(FIXTURES / name, work / name)
    return work / "acme_vpn.json"


@pytest.fixture
def pkgs(tmp_path):
    d = tmp_path / "packages"
    d.mkdir(mode=0o755)
    return d


def truth(manifest, shift=0):
    return vpn_events(manifest, shift)


def go(sample, pkgs, llm, splunk, **kw):
    lines: list[str] = []
    kw.setdefault("stages", ("index-time",))
    result = run(sample, llm, splunk, "pw_test", pkgs, out=lines.append, **kw)
    return result, "\n".join(lines)


def test_pass_on_first_attempt(sample, pkgs, tmp_path, manifest):
    splunk = FakeSplunk([truth(manifest)])
    result, log = go(sample, pkgs, fake_llm(tmp_path, [PROFILE, proposal()]), splunk)
    assert result.status == "passed" and result.attempts == 1
    assert "index-time: PASS (event count 300/300, attempt 1)" in log
    app = splunk.installed[0].app
    assert app.startswith("TA-parsewright-acme-vpn_gateway__test_")
    assert splunk.ingested == [("pw_test", result.sourcetype)]
    assert result.sourcetype.startswith("acme:vpn__test_") and result.sourcetype.endswith("_a1")
    assert splunk.uninstalled == [app] and not list(pkgs.iterdir())  # cleaned up


def test_fix_loop_feeds_evidence_back(sample, pkgs, tmp_path, manifest):
    splunk = FakeSplunk([truth(manifest, shift=-32400), truth(manifest)])
    llm = fake_llm(tmp_path, [PROFILE, proposal(), proposal(tz="Asia/Tokyo")])
    result, _log = go(sample, pkgs, llm, splunk)
    assert result.status == "passed" and result.attempts == 2
    second_prompt = llm._client.requests[2]["messages"][1]["content"]
    assert "most common offset -32400 s" in second_prompt
    # every attempt uses its own sourcetype (Q3, T4.5)
    assert splunk.ingested[0][1].endswith("_a1") and splunk.ingested[1][1].endswith("_a2")


def test_guardrail_block_is_retried_without_deploying(sample, pkgs, tmp_path, manifest):
    splunk = FakeSplunk([truth(manifest)])
    bad = proposal(line_breaker="[\\r\\n]+")  # no capturing group
    llm = fake_llm(tmp_path, [PROFILE, bad, proposal()])
    result, log = go(sample, pkgs, llm, splunk)
    assert result.status == "passed" and result.attempts == 2
    assert "guardrail block: LINE_BREAKER must contain a capturing group" in log
    assert len(splunk.installed) == 1  # the blocked proposal never reached Splunk


def test_budget_exhausted_is_an_honest_failure(sample, pkgs, tmp_path, manifest):
    splunk = FakeSplunk([truth(manifest, shift=3600)] * 2)
    llm = fake_llm(tmp_path, [PROFILE, proposal(), proposal()])
    result, log = go(sample, pkgs, llm, splunk, max_attempts=2)
    assert result.status == "stage_failed" and "index-time: FAIL after 2 attempts" in log
    assert splunk.uninstalled  # cleanup still ran


def test_token_ceiling_stops_and_cleans_up(sample, pkgs, tmp_path, manifest):
    splunk = FakeSplunk([truth(manifest, shift=3600)] * 5)
    llm = fake_llm(tmp_path, [PROFILE, proposal(), proposal()], ceiling=250)
    with pytest.raises(TokenCeilingExceeded):
        go(sample, pkgs, llm, splunk)
    assert splunk.uninstalled


def test_leftover_events_are_never_reused(sample, pkgs, tmp_path, manifest):
    splunk = FakeSplunk([truth(manifest)])
    splunk.count = lambda index, st: 5  # the attempt's sourcetype already has events
    with pytest.raises(RuntimeError, match="already has events"):
        go(sample, pkgs, fake_llm(tmp_path, [PROFILE, proposal()]), splunk)


# --- structured log events --------------------------------------------------------------------

KEYS = {"stage", "attempt", "visit", "actor", "kind", "detail"}


def where(m: dict) -> tuple:
    return (m["stage"], m["attempt"], m["visit"], m["actor"], m["kind"])


def test_every_log_line_carries_its_stage_attempt_actor_and_kind(sample, pkgs, tmp_path, manifest):
    # attempt 1 blocked by the gate, attempt 2 fails the Validator, attempt 3 passes
    replies = [PROFILE, proposal(line_breaker="[\\r\\n]+"), proposal(), proposal(tz="Asia/Tokyo")]
    splunk = FakeSplunk([truth(manifest, shift=-32400), truth(manifest)])
    got, out = collect_events()
    result = run(
        sample,
        fake_llm(tmp_path, replies),
        splunk,
        "pw_test",
        pkgs,
        out=out,
        stages=("index-time",),
        job="evt00001",
    )
    assert result.status == "passed"
    assert all(set(m) == KEYS for _, m in got)
    seq = [where(m) for _, m in got]
    st = "index-time"
    assert seq == [
        (None, None, None, "orchestrator", "start"),
        ("profile", None, None, "profiler", "proposal"),
        ("profile", None, None, "orchestrator", "info"),
        (st, 1, 1, "index_time", "start"),
        (st, 1, 1, "gate", "guardrail_block"),
        (st, 1, 1, "orchestrator", "evidence"),
        (st, 2, 1, "index_time", "start"),
        (st, 2, 1, "index_time", "proposal"),
        (st, 2, 1, "orchestrator", "deploy"),
        (st, 2, 1, "orchestrator", "ingest"),
        (st, 2, 1, "validator", "check_fail"),
        (st, 2, 1, "orchestrator", "evidence"),
        (st, 3, 1, "index_time", "start"),
        (st, 3, 1, "index_time", "proposal"),
        (st, 3, 1, "orchestrator", "deploy"),
        (st, 3, 1, "orchestrator", "ingest"),
        (st, 3, 1, "validator", "check_pass"),
        (st, 3, 1, "validator", "check_pass"),
        (None, None, None, "validator", "info"),  # holdout
        (None, None, None, "orchestrator", "info"),  # tokens used
    ]
    detail = [m["detail"] for _, m in got]
    assert detail[0] == {
        "job_type": "build",
        "file": "acme_vpn.json",
        "events": 300,
        "max_attempts": 5,
        "token_ceiling": 100_000,
        "wall_clock_s": 900,
    }
    assert detail[1]["profile"]["sourcetype"] == "acme:vpn"
    assert detail[3] == {"max_attempts": 5}
    assert "LINE_BREAKER must contain a capturing group" in detail[4]["reason"]
    assert detail[4]["settings"]["line_breaker"] == "[\\r\\n]+"
    assert detail[5]["to"] == st and detail[5]["text"].startswith("blocked: LINE_BREAKER")
    proposed = detail[7]
    assert isinstance(proposed["settings"], dict) and proposed["settings"]["LINE_BREAKER"]
    assert proposed["rationale"] == "one JSON object per line"
    assert detail[8]["app"] == result.app and detail[8]["version"] == "0.0.1"
    assert detail[8]["sourcetype"].endswith("_a2") and len(detail[8]["sha256"]) == 64
    assert detail[9] == {
        "sourcetype": detail[8]["sourcetype"],
        "sets": [{"source": "acme_vpn_json", "events": 300}],
    }
    checks = detail[10]["checks"]
    assert detail[10]["sample_set"] is None and any(not c["passed"] for c in checks)
    assert set(checks[0]) == {"name", "passed", "expected", "actual", "examples"}
    assert "offset -32400 s" in detail[11]["text"]
    assert detail[-2] == {"learned_from": 200, "validated_on": 300}
    assert detail[-1] == {"tokens": result.tokens}
    # the text is what a plain output gets, line for line
    lines: list[str] = []
    replies2 = [PROFILE, proposal(line_breaker="[\\r\\n]+"), proposal(), proposal(tz="Asia/Tokyo")]
    run(
        sample,
        fake_llm(tmp_path, replies2),
        FakeSplunk([truth(manifest, shift=-32400), truth(manifest)]),
        "pw_test",
        pkgs,
        out=lines.append,
        stages=("index-time",),
        job="evt00001",
    )
    assert lines == [line for line, _ in got]
    assert "index-time: PASS (event count 300/300, attempt 3)" in lines
    assert lines[3] == "index-time attempt 1: sourcetype acme:vpn__test_evt00001_a1"


def test_backtrack_events_name_both_stages_and_the_second_visit(
    sample, pkgs, tmp_path, manifest, monkeypatch
):
    def extraction_fails(self):
        self.enter("extraction")
        self.ctx["attempt"] = 1
        self.add_evidence("extraction", {}, "field user: missing")
        return False

    monkeypatch.setattr(Run, "extraction_stage", extraction_fails)
    splunk = FakeSplunk([truth(manifest), truth(manifest)])
    got, out = collect_events()
    llm = fake_llm(tmp_path, [PROFILE, proposal(), proposal()])
    result = run(sample, llm, splunk, "pw_test", pkgs, out=out, stages=("index-time", "extraction"))
    assert result.status == "stage_failed" and result.backtracked
    (back,) = [m for _, m in got if m["kind"] == "backtrack"]
    assert (back["stage"], back["attempt"], back["visit"]) == ("index-time", None, 2)
    assert back["detail"] == {
        "from": "extraction",
        "to": "index-time",
        "because": "field user: missing",
    }
    i = [m for _, m in got].index(back)
    sent = got[i + 1][1]
    assert sent["kind"] == "evidence" and sent["detail"]["to"] == "index-time"
    assert "a later stage (extraction) failed" in sent["detail"]["text"]
    starts = [(m["stage"], m["visit"], m["attempt"]) for _, m in got if m["kind"] == "start"]
    assert starts[1:] == [("index-time", 1, 1), ("index-time", 2, 1)]
    budgets = [m for _, m in got if m["kind"] == "budget"]
    assert [(m["stage"], m["visit"], m["attempt"]) for m in budgets] == [
        ("extraction", 1, None),
        ("extraction", 2, None),
    ]
    assert all(m["detail"] == {"reason": "attempts"} for m in budgets)


def test_profile_review_waits_for_a_human(sample, pkgs, tmp_path):
    got, out = collect_events()
    run(
        sample, fake_llm(tmp_path, [PROFILE]), FakeSplunk([]), "pw_test", pkgs, out=out, review=True
    )
    line, m = got[-1]
    assert line == "profile review: waiting for a human"
    assert where(m) == ("profile", None, None, "human", "human_wait")
    assert m["detail"] == {"for": "profile_review"}
