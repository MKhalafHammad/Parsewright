"""LLM client: OpenAI SDK against the Meta Model API, strict JSON schema output (Q1).

Every call has a timeout, counts tokens against a per-run ceiling, and validates the reply with
Pydantic. Bad output (invalid JSON or cut off) is retried at most twice, separately from the
stage's attempt budget (design "Failure handling").
"""

import copy
import json
import re
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
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
    """Wrap untrusted text as delimited data. Any tag-like text inside it is escaped, so it can
    neither end this block nor pose as another one (appsec Phase 7 L6); <134> (syslog PRI) and
    other non-tags are left as they are."""
    safe = re.sub(r"<(\s*/?\s*[A-Za-z_][\w.-]*\s*/?\s*>)", r"&lt;\1", text)
    safe = re.sub(r"<(/?)\s*" + re.escape(tag), r"&lt;\1" + tag, safe, flags=re.IGNORECASE)
    return f"<{tag}>\n{safe}\n</{tag}>"


PATCH_MODE = """

Patch mode: this sourcetype already has a tested add-on in production, and the log format has
changed (for example after a firmware upgrade). <current_settings> holds this stage's production
settings and <old_format_samples> holds events in the old format. Both formats will coexist, so
the old events must still parse exactly as before. Make the smallest change that makes the new
events pass (add a timestamp option, extend a regex, add an alias); never rewrite settings that
already work. Return this stage's complete settings, changed and unchanged."""


def patch_context(patch: dict | None) -> tuple[str, list[str]]:
    """The patch-mode system suffix and data blocks; nothing outside patch mode."""
    if not patch:
        return "", []
    return PATCH_MODE, [
        as_data("current_settings", json.dumps(patch["current"], indent=1, sort_keys=True)),
        as_data("old_format_samples", "\n".join(patch["old_samples"])),
    ]


class LLMClient:
    def __init__(self, settings: Settings, client: Any = None, timeout: float = 120):
        self.model = settings.llm_model
        self.ceiling = settings.run_token_ceiling
        self.used = 0
        # Worker hooks: guard wraps each model call (kill switch, daily budget, LLM slot);
        # on_usage records the tokens of each call.
        self.guard: Callable[[], AbstractContextManager] = nullcontext
        self.on_usage: Callable[[int], None] = lambda n: None
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
            with self.guard():
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    max_tokens=max_tokens,
                    response_format=fmt,
                )
            usage = getattr(resp, "usage", None)
            # No usage reported: assume the worst, so the ceiling still holds (T6.6).
            n = (usage.prompt_tokens + usage.completion_tokens) if usage else max_tokens
            self.used += n
            self.on_usage(n)
            choice = resp.choices[0]
            if getattr(choice, "finish_reason", None) == "length":
                problem = "reply cut off at the output token cap"
                continue
            try:
                return schema.model_validate_json(choice.message.content or "")
            except (ValidationError, json.JSONDecodeError) as e:
                problem = f"invalid output: {str(e).splitlines()[0]}"
        raise BadOutput(problem)
