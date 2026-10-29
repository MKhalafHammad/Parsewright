import pytest

from parsewright.guardrails.index_time import GuardrailBlock, gate

GOOD = {
    "SHOULD_LINEMERGE": "false",
    "LINE_BREAKER": "([\\r\\n]+)",
    "TIME_FORMAT": "%s",
    "TZ": "UTC",
}


def test_good_settings_pass():
    assert gate(GOOD) == GOOD


@pytest.mark.parametrize(
    "extra",
    [
        {"TRANSFORMS-x": "nullqueue"},  # silent deletion path
        {"INGEST_EVAL": '_raw=""'},
        {"SEDCMD-x": "s/.*//"},
        {"DEST_KEY": "queue"},
        {"KV_MODE": "json"},  # a search-time key: not this stage's
        {"LINEBREAKER": "([\\r\\n]+)"},  # misspelling: splunkd would silently ignore it
    ],
)
def test_unknown_keys_are_blocked(extra):
    with pytest.raises(GuardrailBlock, match="not an allowed"):
        gate(GOOD | extra)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("SHOULD_LINEMERGE", "yes"),
        ("LINE_BREAKER", "[\\r\\n]+"),  # no capturing group
        ("LINE_BREAKER", "(["),
        ("LINE_BREAKER", "(" + "a" * 300 + ")"),
        ("TIME_FORMAT", "YYYY-MM-DD"),
        ("TZ", "Mars/Olympus"),
        ("TZ", "../../etc/passwd"),
        ("MAX_TIMESTAMP_LOOKAHEAD", "0"),
        ("MAX_TIMESTAMP_LOOKAHEAD", "-5"),
        ("TRUNCATE", "0"),  # unlimited
        ("TRUNCATE", "999999999"),
    ],
)
def test_bad_values_are_blocked(key, value):
    with pytest.raises(GuardrailBlock, match=key):
        gate(GOOD | {key: value})


def test_required_keys():
    with pytest.raises(GuardrailBlock, match="LINE_BREAKER is required"):
        gate({"SHOULD_LINEMERGE": "false", "TIME_FORMAT": "%s"})


@pytest.mark.parametrize(
    "fmt,reason",
    [
        ("%N%N%N%N%N%Nx", "side by side"),  # backtracking bomb for the Validator (H1)
        ("%B %A", "side by side"),
        ("%Y" * 13, "at most 12 directives"),
    ],
)
def test_backtracking_time_formats_are_blocked(fmt, reason):
    with pytest.raises(GuardrailBlock, match=reason):
        gate(GOOD | {"TIME_FORMAT": fmt})


def test_no_time_format_is_allowed_only_when_pinned():
    """Two timestamp formats (before and after an upgrade) need Splunk's own recognition."""
    pinned = {k: v for k, v in GOOD.items() if k != "TIME_FORMAT"}
    pinned |= {"TIME_PREFIX": "ts=", "MAX_TIMESTAMP_LOOKAHEAD": "30"}
    assert gate(pinned) == pinned


@pytest.mark.parametrize("missing", ["TIME_PREFIX", "MAX_TIMESTAMP_LOOKAHEAD"])
def test_no_time_format_without_a_pin_is_blocked(missing):
    """Adversarial: unpinned recognition could take bytes=1792483219 as the event time."""
    loose = {k: v for k, v in GOOD.items() if k != "TIME_FORMAT"}
    loose |= {"TIME_PREFIX": "ts=", "MAX_TIMESTAMP_LOOKAHEAD": "30"}
    del loose[missing]
    with pytest.raises(GuardrailBlock, match=f"{missing} is required when TIME_FORMAT"):
        gate(loose)


@pytest.mark.parametrize("pattern", ["((a+)+)$", "(a|a)*$", "((\\w+\\s?)+)$"])
def test_catastrophic_backtracking_is_blocked(pattern):
    with pytest.raises(GuardrailBlock, match="too slow"):
        gate(GOOD | {"LINE_BREAKER": pattern}, samples=["a" * 40])


def test_normal_breakers_pass_the_speed_check():
    samples = ['{"time":"2026-10-20T08:00:46+00:00","user":"alice@example.com"}'] * 50
    assert gate(GOOD | {"TIME_PREFIX": '"time"\\s*:\\s*"'}, samples)
