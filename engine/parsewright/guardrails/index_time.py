"""Index-time gate: allowlisted keys with typed, bounded values (design "Config safety", Q7).

splunkd does not warn about unknown or misspelled keys at runtime, so this allowlist is the only
syntax control: any key not listed here is rejected before Splunk sees it.
"""

import re
import time
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
    deadline = time.monotonic() + 4 * REGEX_TIMEOUT_S  # total budget across all inputs
    for text in [*samples, "\n".join(samples), *STRESS]:
        left = min(REGEX_TIMEOUT_S, deadline - time.monotonic())
        try:
            if left <= 0:
                raise TimeoutError
            compiled.search(text, timeout=left)
        except TimeoutError:
            raise GuardrailBlock(
                "is too slow (catastrophic backtracking); use a simpler pattern"
            ) from None


UNBOUNDED = re.compile(r"(%(?:N|Q|q|B|A|Z)|\s)\s*(?=%(?:N|Q|q|B|A|Z))")
DIRECTIVES = re.compile(r"%(?:[369][NQ]|:z|.)")


def _time_format(value: str) -> str:
    if "%" not in value or len(value) > 100:
        raise GuardrailBlock("must be a strptime format of at most 100 characters")
    if len(DIRECTIVES.findall(value)) > 12:
        raise GuardrailBlock("may use at most 12 directives")
    if UNBOUNDED.search(value):  # e.g. %N%N: ambiguous for Splunk, and slow to check (H1)
        raise GuardrailBlock("may not put two variable-width directives side by side")
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
    "MAX_EVENTS": _int(1, 2000),  # lines per multi-line event; 0 (unlimited) is refused
}
REQUIRED = ("SHOULD_LINEMERGE", "LINE_BREAKER")
# Without TIME_FORMAT Splunk recognises the timestamp itself (the way to accept two formats in
# one sourcetype, e.g. before and after a firmware upgrade; lab-findings Q11). It must then be
# told exactly where to look, so a number elsewhere in the event can never become _time.
UNPINNED_NEEDS = ("TIME_PREFIX", "MAX_TIMESTAMP_LOOKAHEAD")


def gate(settings: dict[str, str], samples: list[str] | None = None) -> dict[str, str]:
    """Return the settings unchanged if every key is allowed and every value valid."""
    for key in settings:
        if key not in ALLOWED:
            raise GuardrailBlock(f"{key} is not an allowed index-time key")
    for key in REQUIRED:
        if key not in settings:
            raise GuardrailBlock(f"{key} is required")
    if "TIME_FORMAT" not in settings:
        for key in UNPINNED_NEEDS:
            if key not in settings:
                raise GuardrailBlock(f"{key} is required when TIME_FORMAT is not set")
    for key, value in settings.items():
        try:
            ALLOWED[key](value)
            if key in ("LINE_BREAKER", "TIME_PREFIX"):
                backtracking_safe(value, samples or [])
        except GuardrailBlock as e:
            raise GuardrailBlock(f"{key} {e}") from None
    return dict(settings)
