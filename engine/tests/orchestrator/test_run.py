import shutil

import pytest
from conftest import FIXTURES, PROFILE, FakeSplunk, fake_llm, proposal, vpn_events

from parsewright.agents.llm import TokenCeilingExceeded
from parsewright.orchestrator.run import run


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
