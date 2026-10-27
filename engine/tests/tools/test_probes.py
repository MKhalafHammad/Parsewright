from types import SimpleNamespace

import openai
import pytest

from parsewright.tools.probes.probe_llm import probe
from parsewright.tools.probes.probe_splunk import require_pw_index

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


def test_invalid_output_counts_as_failure():
    client = FakeClient(lambda **kw: reply(content="not json", tool_args='{"wrong": 1}'))
    assert probe(client, "m") == "none"


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
