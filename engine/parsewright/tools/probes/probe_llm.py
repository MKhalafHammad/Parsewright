"""Probe the model API: which structured-output mode works, and what one call costs.

Run: python -m parsewright.tools.probes.probe_llm  (reads LLM_API_KEY, LLM_BASE_URL, LLM_MODEL)
"""

import json
import os
import re
import sys

import openai
from pydantic import BaseModel, ValidationError


class Answer(BaseModel):
    answer: str


PROMPT = [
    {
        "role": "user",
        "content": 'Reply with the word ok in the field answer, as JSON: {"answer": "ok"}',
    }
]
SCHEMA = Answer.model_json_schema() | {"additionalProperties": False}
TOOL = {"type": "function", "function": {"name": "answer", "parameters": SCHEMA}}
# Room for models that reason before answering; 50 tokens was too few to tell.
MAX_TOKENS = 512


def try_response_format(client, model: str):
    resp = client.chat.completions.create(
        model=model,
        messages=PROMPT,
        max_tokens=MAX_TOKENS,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": SCHEMA, "strict": True},
        },
    )
    return resp, resp.choices[0].message.content


def try_forced_tool(client, model: str):
    resp = client.chat.completions.create(
        model=model,
        messages=PROMPT,
        max_tokens=MAX_TOKENS,
        tools=[TOOL],
        tool_choice={"type": "function", "function": {"name": "answer"}},
    )
    return resp, resp.choices[0].message.tool_calls[0].function.arguments


def try_required_tool(client, model: str):
    resp = client.chat.completions.create(
        model=model, messages=PROMPT, max_tokens=MAX_TOKENS, tools=[TOOL], tool_choice="required"
    )
    return resp, resp.choices[0].message.tool_calls[0].function.arguments


def try_json_object(client, model: str):
    resp = client.chat.completions.create(
        model=model,
        messages=PROMPT,
        max_tokens=MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    return resp, resp.choices[0].message.content


# Long runs of key-like characters: catches a masked, partial or encoded key a server echoes.
KEYLIKE = re.compile(r"[A-Za-z0-9_\-.]{24,}")


def redact(text: str, limit: int = 200) -> str:
    """Remove the API key and key-like runs from the whole text, then cut to one short line.

    Redacting before cutting means a key that crosses the cut cannot leak its first part.
    """
    key = os.environ.get("LLM_API_KEY", "")
    if key:
        text = text.replace(key, "[redacted]")
    text = KEYLIKE.sub("[redacted]", text)
    return " ".join(text.split())[:limit]


def describe_reply(resp, text) -> str:
    """Why a reply failed validation: stop reason, length and the start of the text."""
    finish = getattr(resp.choices[0], "finish_reason", None)
    text = text or ""
    return f"finish_reason={finish} chars={len(text)} starts={redact(repr(text), 120)}"


def describe_error(e: Exception) -> str:
    status = getattr(e, "status_code", "")
    message = getattr(e, "message", "") or str(e)
    return f"{type(e).__name__} {status} {redact(message)}".replace("  ", " ")


def probe(client, model: str) -> str:
    """Return the first structured-output mode that works, printing usage or why each failed."""
    for name, attempt in (
        ("response_format", try_response_format),
        ("forced_tool", try_forced_tool),
        ("required_tool", try_required_tool),
        ("json_object", try_json_object),
    ):
        try:
            resp, text = attempt(client, model)
        except (openai.OpenAIError, IndexError, TypeError, AttributeError) as e:
            # Error class, status and the server's message only: never echo the request.
            print(f"{name}: FAIL ({describe_error(e)})")
            continue
        try:
            Answer.model_validate_json(text)
        except (ValidationError, json.JSONDecodeError, TypeError):
            print(f"{name}: FAIL (invalid output: {describe_reply(resp, text)})")
            continue
        usage = resp.usage
        print(f"{name}: PASS (tokens in={usage.prompt_tokens} out={usage.completion_tokens})")
        return name
    return "none"


def main() -> int:
    client = openai.OpenAI(
        api_key=os.environ["LLM_API_KEY"], base_url=os.environ["LLM_BASE_URL"], timeout=30
    )
    mode = probe(client, os.environ["LLM_MODEL"])
    print(f"structured output mode: {mode}")
    return 0 if mode != "none" else 1


if __name__ == "__main__":
    sys.exit(main())
