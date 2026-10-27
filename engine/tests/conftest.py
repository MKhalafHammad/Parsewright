"""Shared fakes: no real network in tests. Splunk and the model are always faked."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from parsewright.agents.llm import LLMClient
from parsewright.config import Settings

FIXTURES = Path(__file__).parents[1] / "parsewright" / "generator" / "fixtures"


def settings(tmp_path: Path, ceiling: int = 100_000) -> Settings:
    return Settings(
        llm_api_key="test-key",
        llm_base_url="https://llm.example.com/v1",
        llm_model="test-model",
        splunk_host="splunk.example.com",
        splunk_port=8089,
        splunk_search_token="search-token",
        splunk_deploy_token="deploy-token",
        packages_dir=tmp_path,
        test_index="pw_test",
        run_token_ceiling=ceiling,
    )


def completion(content: str, finish: str = "stop", tokens: int = 100):
    usage = SimpleNamespace(prompt_tokens=tokens // 2, completion_tokens=tokens - tokens // 2)
    choice = SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish)
    return SimpleNamespace(choices=[choice], usage=usage)


class FakeOpenAI:
    """Replies with each queued item in turn; an item is a dict (JSON reply) or a completion."""

    def __init__(self, replies: list):
        self.replies = list(replies)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        item = self.replies.pop(0)
        return completion(json.dumps(item)) if isinstance(item, dict) else item


def fake_llm(tmp_path: Path, replies: list, ceiling: int = 100_000) -> LLMClient:
    return LLMClient(settings(tmp_path, ceiling), client=FakeOpenAI(replies))


PROFILE = {
    "format": "json",
    "multiline": False,
    "timestamp_example": "2026-10-20T08:00:46+00:00",
    "timestamp_format_candidates": ["%Y-%m-%dT%H:%M:%S%:z"],
    "timezone_in_timestamp": True,
    "timezone_hint": None,
    "vendor": "Acme",
    "product": "VPN Gateway",
    "sourcetype": "acme:vpn",
    "event_categories": ["auth", "session"],
    "fields": [{"name": "user", "coverage": 1.0}],
    "cim_targets": ["Authentication"],
}


def proposal(tz: str | None = None, line_breaker: str = "([\\r\\n]+)") -> dict:
    return {
        "should_linemerge": False,
        "line_breaker": line_breaker,
        "time_prefix": '"time":"',
        "time_format": "%Y-%m-%dT%H:%M:%S%:z",
        "max_timestamp_lookahead": 32,
        "tz": tz,
        "truncate": None,
        "rationale": "one JSON object per line",
    }


class FakeSplunk:
    """Records calls; each ingest makes the next queued event list visible for that sourcetype."""

    def __init__(self, per_attempt: list[list[tuple[int, str]]], warnings=None):
        self.per_attempt = list(per_attempt)
        self.warnings = warnings or []
        self.installed: list = []
        self.uninstalled: list[str] = []
        self.ingested: list[tuple[str, str]] = []
        self.data: dict[str, list[tuple[int, str]]] = {}

    def install(self, pkg):
        self.installed.append(pkg)

    def uninstall(self, app):
        self.uninstalled.append(app)

    def ingest(self, index, sourcetype, body, source):
        self.ingested.append((index, sourcetype))
        self.data[sourcetype] = self.per_attempt.pop(0)

    def count(self, index, sourcetype):
        return len(self.data.get(sourcetype, []))

    def wait_stable(self, index, sourcetype):
        return self.count(index, sourcetype)

    def events(self, index, sourcetype):
        return self.data.get(sourcetype, [])

    def parser_warnings(self, sourcetype, since, app, caught_up_to):
        if isinstance(self.warnings, Exception):
            raise self.warnings
        return self.warnings


@pytest.fixture
def manifest() -> dict:
    return json.loads((FIXTURES / "acme_vpn.manifest.json").read_text())
