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


# --- a log without a truth manifest (validated mechanically) ---------------------------------


@pytest.fixture
def no_manifest(tmp_path):
    """The Tokyo-time VPN log with no manifest beside it: what a real upload looks like."""
    work = tmp_path / "real"
    work.mkdir()
    shutil.copy(FIXTURES / "acme_vpn_notz.json", work / "vpn.json")
    return work / "vpn.json"


NOTZ = PROFILE | {"timezone_in_timestamp": False, "timezone_hint": "Asia/Tokyo"}


def notz_proposal(tz: str | None) -> dict:
    return proposal(tz=tz) | {"time_format": "%Y-%m-%d %H:%M:%S", "max_timestamp_lookahead": 19}


def notz_events(shift: int = 0) -> list[tuple[int, str]]:
    import json

    lines = [ln for ln in (FIXTURES / "acme_vpn_notz.json").read_text().splitlines() if ln]
    epochs = json.loads((FIXTURES / "acme_vpn_notz.manifest.json").read_text())["epochs"]
    return [(e + shift, raw) for e, raw in zip(epochs, lines, strict=True)]


def test_a_log_without_a_zone_waits_for_a_human_even_when_review_is_skipped(
    no_manifest, pkgs, tmp_path
):
    """Nothing in the file says which zone 2026-10-20 17:00:46 is in; the AI's hint is only a
    suggestion, so the run pauses before building (no Splunk work, one model call)."""
    got, out = collect_events()
    splunk = FakeSplunk([])
    llm = fake_llm(tmp_path, [NOTZ])
    result = run(no_manifest, llm, splunk, "pw_test", pkgs, out=out, stages=("index-time",))
    assert result.status == "profile_review" and not splunk.installed
    line, m = got[-1]
    assert "carry no timezone" in line and m["detail"]["reason"] == "timezone"
    assert len(llm._client.requests) == 1


def test_epoch_or_offset_timestamps_need_no_timezone_whatever_the_profile_says(
    no_manifest, pkgs, tmp_path
):
    """Code reads the example: an epoch is UTC by definition (the lab's Profiler said "no zone"
    for 1792483254000 and the run paused for nothing)."""
    from parsewright.validator.mechanical import example_has_zone

    text = (
        'ts=1792483254000 a=1\n{"time":"2026-10-20T08:00:46+00:00"}\n{"time":"2026-10-20 17:00:45"}'
    )
    assert example_has_zone("1792483254000", text, profile_says=False)
    assert example_has_zone("2026-10-20T08:00:46+00:00", text, profile_says=False)
    assert not example_has_zone("2026-10-20 17:00:45", text, profile_says=True)
    assert example_has_zone("made up", text, profile_says=True)  # not in the file: the flag


def test_a_stated_timezone_is_the_one_the_add_on_must_use(no_manifest, pkgs, tmp_path):
    """The form said Asia/Tokyo: a proposal with TZ=UTC fails (every event 9 h off, read by
    code from the raw line), the evidence goes back, and TZ=Asia/Tokyo passes."""
    splunk = FakeSplunk([notz_events(shift=32400), notz_events()])
    llm = fake_llm(tmp_path, [NOTZ, notz_proposal("UTC"), notz_proposal("Asia/Tokyo")])
    result, log = go(no_manifest, pkgs, llm, splunk, timezone="Asia/Tokyo")
    assert result.status == "passed" and result.attempts == 2, log
    # Splunk's times agree with a UTC reading, so only the stated zone exposes the guess.
    first = log.split("index-time attempt 2")[0]
    assert "PASS timestamp accuracy" in first and "FAIL timezone" in first
    second = llm._client.requests[2]["messages"][1]["content"]
    assert "confirmed timezone is Asia/Tokyo" in second


def test_code_not_the_profile_decides_whether_timestamps_carry_a_zone(no_manifest, pkgs, tmp_path):
    """Adversarial: the profile wrongly says the timestamps carry a zone, and the agent's
    TZ=UTC makes every check pass. Code reads the lines, finds no zone, and the run goes
    back to profile review instead of shipping a guessed timezone."""
    wrong = NOTZ | {"timezone_in_timestamp": True, "timezone_hint": None}
    checkpoints: list[dict] = []
    splunk = FakeSplunk([notz_events(shift=32400)])
    llm = fake_llm(tmp_path, [wrong, notz_proposal("UTC")])
    result, log = go(no_manifest, pkgs, llm, splunk, checkpoint=checkpoints.append)
    assert result.status == "profile_review", log
    assert checkpoints[-1]["needs_timezone"] and checkpoints[-1]["stage_index"] == 0
    assert "carry no timezone" in log


def test_a_generator_sample_keeps_its_answer_key(sample, pkgs, tmp_path, manifest):
    """With its manifest beside it, the run validates against the truth as before."""
    splunk = FakeSplunk([truth(manifest)])
    result, log = go(sample, pkgs, fake_llm(tmp_path, [PROFILE, proposal()]), splunk)
    assert result.status == "passed" and "FAIL timezone" not in log
    assert "timestamp accuracy: expected all _time = manifest" in log


def test_value_pairs_match_events_across_the_cim_layer(sample, pkgs, tmp_path):
    """action=accept becomes action=allowed under the same name; and an EVAL reading two
    fields shows each event's own source value (lab: logins use result, sessions verdict)."""
    from parsewright.orchestrator.caps import IngestCaps
    from parsewright.validator.mechanical import RAW

    class Rows(FakeSplunk):
        def field_rows(self, index, sourcetype, source=None):
            return [
                {RAW: "a", "action": "allowed"},
                {RAW: "b", "action": "failure"},
                {RAW: "c", "action": "failure"},
            ]

    r = Run(
        sample,
        fake_llm(tmp_path, []),
        Rows([]),
        "pw_test",
        pkgs,
        print,
        5,
        IngestCaps(None, 20, 500),
    )
    r.pre_cim = [
        {RAW: "a", "action": "accept"},
        {RAW: "b", "result": "failure"},
        {RAW: "c", "result": "failure"},
    ]
    single = r.value_pairs(["action"], "action", None)
    assert {"from": "accept", "to": "allowed", "count": 1} in single
    pairs = r.value_pairs(["action", "result"], "action", None)
    assert {"from": "result=failure", "to": "failure", "count": 2} in pairs


def test_source_variety_is_read_before_the_cim_layer(sample, pkgs, tmp_path):
    """appsec H1: EVAL-action = case(action=="accept","allowed",true(),"allowed") rewrites
    its own source, so variety must come from the pre-CIM snapshot; an enumerated field is
    judged even when its EVAL reads two fields."""
    from parsewright.agents.profiler import LogProfile
    from parsewright.orchestrator.caps import IngestCaps

    r = Run(
        sample,
        fake_llm(tmp_path, []),
        FakeSplunk([]),
        "pw_test",
        pkgs,
        print,
        5,
        IngestCaps(None, 20, 500),
    )
    r.pre_cim = [{"action": a, "src": "x", "dest": "y"} for a in ("accept", "drop", "reset")]
    prof = LogProfile(**PROFILE | {"fields": [{"name": "action", "coverage": 1.0}]})
    faked = {"props": {"EVAL-action": 'case(action=="accept","allowed",true(),"allowed")'}}
    assert r.source_distinct(faked, prof, None)["action"] == 3
    two = {"props": {"EVAL-action": 'if(len(src)>0 AND len(action)>0,"allowed","allowed")'}}
    assert r.source_distinct(two, prof, None)["action"] == 3
