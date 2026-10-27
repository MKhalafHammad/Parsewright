"""Index-time gate: allowlisted keys with typed, bounded values (design "Config safety", Q7).

splunkd does not warn about unknown or misspelled keys at runtime, so this allowlist is the only
syntax control: any key not listed here is rejected before Splunk sees it.
"""

from collections.abc import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import regex


class GuardrailBlock(ValueError):
    """A proposal the gate refuses; the message goes back to the agent as the block reason."""


def _bool(value: str) -> str:
    if value not in ("true", "false"):
        raise GuardrailBlock("must be true or false")
    return value


def _int(low: int, high: int) -> Callable[[str], str]:
    def check(value: str) -> str:
        if not value.isdigit() or not low <= int(value) <= high:
            raise GuardrailBlock(f"must be an integer from {low} to {high}")
        return value

    return check


REGEX_TIMEOUT_S = 0.2
# Inputs that make catastrophic backtracking show up quickly (T2.10).
STRESS = ["a" * 5000 + "!", " " * 5000 + "!", "\n" * 2000 + "x", "=" * 5000 + "!"]


def _regex(need_group: bool) -> Callable[[str], str]:
    def check(value: str) -> str:
        if not value or len(value) > 200:
            raise GuardrailBlock("must be a regex of 1 to 200 characters")
        try:
            compiled = regex.compile(value)
        except regex.error as e:
            raise GuardrailBlock(f"is not a valid regex: {e}") from None
        if need_group and compiled.groups < 1:
            raise GuardrailBlock("must contain a capturing group (the text Splunk discards)")
        return value

    return check


def backtracking_safe(value: str, samples: list[str]) -> None:
    """Run the regex over the samples and stress inputs with a timeout; slow means blocked."""
    compiled = regex.compile(value)
    for text in [*samples, "\n".join(samples), *STRESS]:
        try:
            compiled.search(text, timeout=REGEX_TIMEOUT_S)
        except TimeoutError:
            raise GuardrailBlock(
                "is too slow (catastrophic backtracking); use a simpler pattern"
            ) from None


def _time_format(value: str) -> str:
    if "%" not in value or len(value) > 100:
        raise GuardrailBlock("must be a strptime format of at most 100 characters")
    return value


def _tz(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise GuardrailBlock("must be an IANA time zone such as UTC or Asia/Tokyo") from None
    return value


ALLOWED: dict[str, Callable[[str], str]] = {
    "SHOULD_LINEMERGE": _bool,
    "LINE_BREAKER": _regex(need_group=True),
    "TIME_PREFIX": _regex(need_group=False),
    "TIME_FORMAT": _time_format,
    "MAX_TIMESTAMP_LOOKAHEAD": _int(1, 128),
    "TZ": _tz,
    "TRUNCATE": _int(256, 100_000),  # 0 (unlimited) is refused: giant events (design bounds)
}
REQUIRED = ("SHOULD_LINEMERGE", "LINE_BREAKER", "TIME_FORMAT")


def gate(settings: dict[str, str], samples: list[str] | None = None) -> dict[str, str]:
    """Return the settings unchanged if every key is allowed and every value valid."""
    for key in settings:
        if key not in ALLOWED:
            raise GuardrailBlock(f"{key} is not an allowed index-time key")
    for key in REQUIRED:
        if key not in settings:
            raise GuardrailBlock(f"{key} is required")
    for key, value in settings.items():
        try:
            ALLOWED[key](value)
            if key in ("LINE_BREAKER", "TIME_PREFIX"):
                backtracking_safe(value, samples or [])
        except GuardrailBlock as e:
            raise GuardrailBlock(f"{key} {e}") from None
    return dict(settings)
