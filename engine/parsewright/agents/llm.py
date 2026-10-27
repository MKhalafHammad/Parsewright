"""LLM client: OpenAI SDK against the Meta Model API, strict JSON schema output (Q1).

Every call has a timeout, counts tokens against a per-run ceiling, and validates the reply with
Pydantic. Bad output (invalid JSON or cut off) is retried at most twice, separately from the
stage's attempt budget (design "Failure handling").
"""

import copy
import json
import re
from typing import Any

import openai
from pydantic import BaseModel, ValidationError

from parsewright.config import Settings

BAD_OUTPUT_RETRIES = 2
# The model reasons before it answers (a one-word reply used ~300 output tokens), so caps need
# headroom on top of the expected JSON.
DEFAULT_MAX_TOKENS = 8192


class TokenCeilingExceeded(RuntimeError):
    pass


class BadOutput(RuntimeError):
    pass


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema in strict form: every object closed and every property required."""
    schema = copy.deepcopy(model.model_json_schema())

    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for value in node.values():
                close(value)
        elif isinstance(node, list):
            for value in node:
                close(value)

    close(schema)
    return schema


def as_data(tag: str, text: str) -> str:
    """Wrap untrusted text as delimited data; a closing tag inside it cannot end the block."""
    safe = re.sub(r"<(/?)\s*" + re.escape(tag), r"&lt;\1" + tag, text, flags=re.IGNORECASE)
    return f"<{tag}>\n{safe}\n</{tag}>"


class LLMClient:
    def __init__(self, settings: Settings, client: Any = None, timeout: float = 120):
        self.model = settings.llm_model
        self.ceiling = settings.run_token_ceiling
        self.used = 0
        self._client = client or openai.OpenAI(
            api_key=settings.llm_api_key, base_url=settings.llm_base_url, timeout=timeout
        )

    def structured[T: BaseModel](
        self, system: str, user: str, schema: type[T], max_tokens: int = DEFAULT_MAX_TOKENS
    ) -> T:
        """One schema-validated answer, or BadOutput after the retry cap."""
        fmt = {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__,
                "schema": strict_schema(schema),
                "strict": True,
            },
        }
        problem = ""
        for _ in range(1 + BAD_OUTPUT_RETRIES):
            if self.used >= self.ceiling:
                raise TokenCeilingExceeded(f"run token ceiling {self.ceiling} reached")
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=max_tokens,
                response_format=fmt,
            )
            usage = getattr(resp, "usage", None)
            # No usage reported: assume the worst, so the ceiling still holds (T6.6).
            self.used += (usage.prompt_tokens + usage.completion_tokens) if usage else max_tokens
            choice = resp.choices[0]
            if getattr(choice, "finish_reason", None) == "length":
                problem = "reply cut off at the output token cap"
                continue
            try:
                return schema.model_validate_json(choice.message.content or "")
            except (ValidationError, json.JSONDecodeError) as e:
                problem = f"invalid output: {str(e).splitlines()[0]}"
        raise BadOutput(problem)
