"""Probe the model API: which structured-output mode works, and what one call costs.

Run: python -m parsewright.tools.probes.probe_llm  (reads LLM_API_KEY, LLM_BASE_URL, LLM_MODEL)
"""

import json
import os
import sys

import openai
from pydantic import BaseModel, ValidationError


class Answer(BaseModel):
    answer: str


PROMPT = [{"role": "user", "content": "Reply with the word ok in the field answer."}]
SCHEMA = Answer.model_json_schema() | {"additionalProperties": False}


def try_response_format(client, model: str):
    resp = client.chat.completions.create(
        model=model,
        messages=PROMPT,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": SCHEMA, "strict": True},
        },
    )
    Answer.model_validate_json(resp.choices[0].message.content)
    return resp.usage


def try_forced_tool(client, model: str):
    resp = client.chat.completions.create(
        model=model,
        messages=PROMPT,
        tools=[{"type": "function", "function": {"name": "answer", "parameters": SCHEMA}}],
        tool_choice={"type": "function", "function": {"name": "answer"}},
    )
    Answer.model_validate_json(resp.choices[0].message.tool_calls[0].function.arguments)
    return resp.usage


def probe(client, model: str) -> str:
    """Return the first structured-output mode that works, printing usage or why each failed."""
    for name, attempt in (
        ("response_format", try_response_format),
        ("forced_tool", try_forced_tool),
    ):
        try:
            usage = attempt(client, model)
        except (
            openai.OpenAIError,
            ValidationError,
            json.JSONDecodeError,
            IndexError,
            TypeError,
        ) as e:
            # Error class and HTTP status only: never echo request details.
            print(f"{name}: FAIL ({type(e).__name__} {getattr(e, 'status_code', '')})".rstrip())
            continue
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
