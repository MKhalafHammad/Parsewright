"""The bootstrap waits for the KV store before it touches tokens."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "splunk_bootstrap.py"


@pytest.fixture
def bootstrap(monkeypatch):
    monkeypatch.setenv("SPLUNK_PASSWORD", "test-only")
    spec = importlib.util.spec_from_file_location("splunk_bootstrap", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return module


def test_wait_tokens_retries_until_the_kv_store_answers(bootstrap, monkeypatch):
    replies = iter([(503, None), (503, None), (200, {})])
    monkeypatch.setattr(bootstrap, "call", lambda *_: next(replies))
    bootstrap.wait_tokens()
    assert next(replies, None) is None


def test_wait_tokens_fails_when_the_kv_store_never_answers(bootstrap, monkeypatch):
    monkeypatch.setattr(bootstrap, "call", lambda *_: (503, None))
    with pytest.raises(SystemExit):
        bootstrap.wait_tokens(limit=0)


def test_roles_hold_exactly_the_capabilities_they_need(bootstrap):
    """Too few breaks a clean install (403 on config reads); more widens a stolen token."""
    caps = {role: set(spec["capabilities"]) for role, spec in bootstrap.ROLES.items()}
    assert caps == {
        "parsewright_search": {"list_all_objects", "search"},
        "parsewright_deploy": {
            "admin_all_objects",
            "edit_tcp",
            "install_apps",
            "list_all_objects",
        },
        "parsewright_drift": {"search"},
    }
