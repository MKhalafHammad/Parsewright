import base64
import json
import time
from types import SimpleNamespace

import openai
import pytest

from parsewright.tools.probes.probe_llm import probe, redact
from parsewright.tools.probes.probe_splunk import require_pw_index, token_shape

USAGE = SimpleNamespace(prompt_tokens=10, completion_tokens=3)


def reply(content=None, tool_args=None):
    call = SimpleNamespace(function=SimpleNamespace(arguments=tool_args))
    msg = SimpleNamespace(content=content, tool_calls=[call] if tool_args else None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=USAGE)


class FakeClient:
    def __init__(self, handler):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=handler))


def test_response_format_preferred():
    client = FakeClient(lambda **kw: reply(content='{"answer": "ok"}'))
    assert probe(client, "m") == "response_format"


def test_falls_back_to_forced_tool():
    def handler(**kw):
        if "response_format" in kw:
            raise openai.OpenAIError("response_format unsupported")
        return reply(tool_args='{"answer": "ok"}')

    assert probe(FakeClient(handler), "m") == "forced_tool"


def test_falls_back_to_required_tool():
    def handler(**kw):
        if kw.get("tool_choice") != "required":
            raise openai.OpenAIError("unsupported")
        return reply(tool_args='{"answer": "ok"}')

    assert probe(FakeClient(handler), "m") == "required_tool"


def test_falls_back_to_json_object():
    def handler(**kw):
        if kw.get("response_format") != {"type": "json_object"}:
            raise openai.OpenAIError("unsupported")
        return reply(content='{"answer": "ok"}')

    assert probe(FakeClient(handler), "m") == "json_object"


def test_invalid_output_counts_as_failure(capsys):
    client = FakeClient(lambda **kw: reply(content="not json", tool_args='{"wrong": 1}'))
    assert probe(client, "m") == "none"
    assert "starts='not json'" in capsys.readouterr().out


def test_failure_output_redacts_api_key(monkeypatch, capsys):
    monkeypatch.setenv("LLM_API_KEY", "sk-test-secret-value")

    def handler(**kw):
        raise openai.OpenAIError("bad request for key sk-test-secret-value")

    assert probe(FakeClient(handler), "m") == "none"
    out = capsys.readouterr().out
    assert "sk-test-secret-value" not in out
    assert "[redacted]" in out


@pytest.mark.parametrize(
    "index",
    [
        "main",
        "pw",
        "pw_",
        "pw_*",
        "pw_x | delete",
        "pw_x OR index=main",
        "_internal",
        "PW_x",
        "xpw_probe",
    ],
)
def test_rejects_non_pw_index(index):
    with pytest.raises(ValueError):
        require_pw_index(index)


def test_accepts_pw_index():
    assert require_pw_index("pw_probe") == "pw_probe"


def fake_jwt(claims: dict, signature: str = "c2VjcmV0LXNpZ25hdHVyZQ") -> str:
    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'HS512'})}.{b64(claims)}.{signature}"


def test_token_shape_reports_user_and_expiry_but_not_the_token():
    token = fake_jwt({"sub": "parsewright_deploy", "exp": int(time.time()) + 7200})
    shape = token_shape(token)
    assert "user=parsewright_deploy" in shape
    assert "expires in 1h" in shape or "expires in 2h" in shape
    assert token not in shape
    assert "c2VjcmV0LXNpZ25hdHVyZQ" not in shape


def test_token_shape_flags_expired_quoted_and_truncated_tokens():
    assert "EXPIRED" in token_shape(fake_jwt({"sub": "u", "exp": 1}))
    assert "quote" in token_shape('"' + fake_jwt({"sub": "u"}) + '"')
    assert "whitespace" in token_shape(fake_jwt({"sub": "u"}) + " ")
    assert "not a JWT" in token_shape("abc.def")


def test_redact_runs_before_the_cut(monkeypatch):
    key = "sk-" + "a" * 40
    monkeypatch.setenv("LLM_API_KEY", key)
    text = "x" * 110 + key
    out = redact(text, 120)
    assert "sk-aaa" not in out and "aaaa" not in out


def test_redact_masks_partial_or_masked_keys(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-" + "b" * 40)
    out = redact("invalid key sk-bbbbbbbbbbbbbbbbbbbbbbbbbbbb... (truncated)")
    assert "bbbbbbbbbbbbbbbbbbbbbbbb" not in out


def test_token_shape_edge_cases():
    assert "empty" in token_shape("")
    assert "not a JSON object" in token_shape(fake_jwt_raw("[1, 2]"))
    assert "expiry not a number" in token_shape(fake_jwt({"sub": "u", "exp": "soon"}))


def fake_jwt_raw(payload: str) -> str:
    b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzUxMiJ9.{b64}.sig"
