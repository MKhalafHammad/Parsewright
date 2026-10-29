"""Index-time Validator: fixed checks, no AI (design "Validation design").

Ground truth is the generator's truth manifest: event count and the true epoch of each event.
"""

import re
import time
from collections import Counter
from dataclasses import dataclass, field

import regex

from parsewright.tools.splunk_client import SplunkClient

MAX_EXAMPLES = 3
RAW_PREVIEW = 300
# splunkd lines carry host names and paths and are text the model could be steered by (T1.2),
# so the agent only ever sees these fixed summaries; the raw lines stay in operator output.
WARNING_SUMMARIES = {
    "DateParserVerbose": "DateParserVerbose: Splunk could not parse, or distrusted, a timestamp",
    "LineBreakingProcessor": "LineBreakingProcessor: a line was truncated or broken badly",
    "AggregatorMiningProcessor": "AggregatorMiningProcessor: events were merged or split badly",
}
COMPONENT = re.compile("|".join(WARNING_SUMMARIES))


@dataclass
class Check:
    name: str
    passed: bool
    expected: str
    actual: str
    examples: list[str] = field(default_factory=list)
    operator_detail: list[str] = field(default_factory=list)  # never sent to the model


@dataclass
class Report:
    checks: list[Check]

    @property
    def passed(self) -> bool:
        # No checks is not a pass: an empty report must never move a run forward (M1).
        return bool(self.checks) and all(c.passed for c in self.checks)

    def evidence(self) -> str:
        """Failed checks as text for the owning agent: expected, actual, up to 3 events."""
        lines = []
        for c in self.checks:
            if c.passed:
                continue
            lines.append(f"FAILED {c.name}: expected {c.expected}, actual {c.actual}")
            lines.extend(f"  event: {e}" for e in c.examples)
        return "\n".join(lines)


def _preview(raw: str) -> str:
    """Short, printable: control characters and terminal escapes are shown escaped."""
    return raw[:RAW_PREVIEW].encode("unicode_escape").decode("ascii")


def check_count(actual: int, expected: int, events: list[tuple[int, str]]) -> Check:
    examples = [] if actual == expected else [_preview(r) for _, r in events[:MAX_EXAMPLES]]
    return Check("event count", actual == expected, str(expected), str(actual), examples)


def check_times(events: list[tuple[int, str]], expected: list[int]) -> Check:
    actual = [t for t, _ in events]
    if len(actual) != len(expected):
        return Check(
            "timestamp accuracy",
            False,
            f"{len(expected)} events with manifest epochs",
            f"{len(actual)} events (fix the event count first)",
        )
    pairs = list(zip(sorted(actual), sorted(expected), strict=True))
    wrong = [(a, e) for a, e in pairs if a != e]
    if not wrong:
        return Check("timestamp accuracy", True, "all _time = manifest", "all match")
    offset, n = Counter(a - e for a, e in wrong).most_common(1)[0]
    by_time = dict(events)
    examples = [f"_time={a} expected={e} raw={_preview(by_time.get(a, ''))}" for a, e in wrong[:3]]
    return Check(
        "timestamp accuracy",
        False,
        "_time equal to the manifest epoch for every event",
        f"{len(wrong)}/{len(pairs)} events wrong; most common offset {offset:+d} s on {n} events",
        examples,
    )


# Splunk strptime directives as patterns, to check that TIME_FORMAT really matches the events.
# When it does not, Splunk silently falls back to guessing the timestamp (lab, Phase 7): the
# times can still come out right, but only by luck, so the add-on is not correct.
DIRECTIVES = {
    "%Y": r"\d{4}",
    "%y": r"\d{2}",
    "%m": r"\d{1,2}",
    "%d": r"\d{1,2}",
    "%e": r"\s?\d{1,2}",
    "%H": r"\d{1,2}",
    "%I": r"\d{1,2}",
    "%M": r"\d{2}",
    "%S": r"\d{2}",
    "%p": r"[AaPp][Mm]",
    "%b": r"[A-Za-z]{3}",
    "%h": r"[A-Za-z]{3}",
    "%B": r"[A-Za-z]+",
    "%a": r"[A-Za-z]{3}",
    "%A": r"[A-Za-z]+",
    "%j": r"\d{1,3}",
    "%s": r"\d{9,10}",
    "%3N": r"\d{3}",
    "%6N": r"\d{6}",
    "%9N": r"\d{9}",
    "%N": r"\d+",
    "%z": r"(?:[+-]\d{2}:?\d{2}|Z)",
    "%:z": r"[+-]\d{2}:\d{2}",
    "%Z": r"[A-Za-z][A-Za-z0-9+_/-]*",
    "%T": r"\d{2}:\d{2}:\d{2}",
    "%F": r"\d{4}-\d{2}-\d{2}",
    "%D": r"\d{2}/\d{2}/\d{2}",
    "%R": r"\d{2}:\d{2}",
    "%r": r"\d{2}:\d{2}:\d{2}\s+[AaPp][Mm]",
    "%k": r"\s?\d{1,2}",
    "%l": r"\s?\d{1,2}",
    "%Q": r"\d{1,9}",
    "%q": r"\d{1,9}",
    "%3Q": r"\d{3}",
    "%6Q": r"\d{6}",
    "%u": r"[1-7]",
    "%w": r"[0-6]",
    "%%": "%",
}
DIRECTIVE = re.compile(r"%(?:[369][NQ]|:z|.)")
FORMAT_CHECK_S = 2.0  # one deadline for the whole check, across every event (appsec Phase 7)


def format_pattern(fmt: str) -> str | None:
    """TIME_FORMAT as a regex, or None if it uses a directive not in DIRECTIVES."""
    out, pos = [], 0
    for m in DIRECTIVE.finditer(fmt):
        out.append(re.sub(r"\\ ", r"\\s+", re.escape(fmt[pos : m.start()])))
        if m.group(0) not in DIRECTIVES:
            return None
        out.append(DIRECTIVES[m.group(0)])
        pos = m.end()
    out.append(re.sub(r"\\ ", r"\\s+", re.escape(fmt[pos:])))
    return "".join(out)


def check_time_format(settings: dict[str, str] | None, events: list[tuple[int, str]]) -> Check:
    """Every event's timestamp matches TIME_FORMAT where TIME_PREFIX says it starts.

    Fails closed: an unlisted directive, or running out of the check's time budget, fails it.
    Both patterns run on the `regex` module with timeouts, so no format can hang a worker."""
    name, expected = "TIME_FORMAT matches", "TIME_FORMAT matches every event at TIME_PREFIX"
    fmt = (settings or {}).get("TIME_FORMAT")
    if not fmt:
        return Check(name, True, expected, "not set: Splunk recognises each pinned timestamp")
    pattern = format_pattern(fmt)
    if pattern is None:
        return Check(
            name,
            False,
            expected,
            f"{fmt!r} uses a directive this check cannot verify; use the listed ones "
            "(%Y %m %d %H %M %S %s %3N %z %b ...)",
        )
    prefix = settings.get("TIME_PREFIX")
    look = int(settings.get("MAX_TIMESTAMP_LOOKAHEAD") or 128)
    compiled = regex.compile(r"\s*" + pattern if prefix else pattern)
    deadline = time.monotonic() + FORMAT_CHECK_S
    bad = []
    for _, raw in events:
        left = deadline - time.monotonic()
        if left <= 0:
            return Check(name, False, expected, "check ran out of time: simplify TIME_FORMAT")
        try:
            if prefix:
                m = regex.search(prefix, raw, timeout=left)
                ok = m is not None and compiled.match(raw[m.end() : m.end() + look], timeout=left)
            else:
                ok = compiled.search(raw[:look], timeout=left)
        except TimeoutError:
            return Check(name, False, expected, "check ran out of time: simplify TIME_FORMAT")
        if not ok:
            bad.append(raw)
    return Check(
        name,
        not bad,
        expected,
        f"{len(bad)} events where it does not (Splunk only guessed their timestamps)"
        if bad
        else "all match",
        [_preview(raw) for raw in bad[:MAX_EXAMPLES]],
    )


def summarise(warning: str) -> str:
    match = COMPONENT.search(warning)
    return WARNING_SUMMARIES[match.group(0)] if match else "Splunk message about this add-on"


def check_fallback(events: list[tuple[int, int, str]]) -> Check:
    """Events whose _time is within 60 s of _indextime: Splunk fell back to the index time."""
    bad = [(t, raw) for t, it, raw in events if it and abs(it - t) < 60]
    return Check(
        "timestamp fallback",
        not bad,
        "0 events with |_indextime - _time| < 60 s",
        f"{len(bad)} events"
        + (" (timestamp not parsed: Splunk used the index time)" if bad else ""),
        [_preview(raw) for _, raw in bad[:MAX_EXAMPLES]],
    )


def check_warnings(warnings: list[str] | None) -> Check:
    if warnings is None:  # the check itself failed: fail closed (Q7)
        return Check("parser warnings", False, "0", "check could not run")
    summaries = list(dict.fromkeys(summarise(w) for w in warnings))
    return Check(
        "parser warnings",
        not warnings,
        "0",
        str(len(warnings)),
        summaries[:MAX_EXAMPLES],
        [_preview(w) for w in warnings[:MAX_EXAMPLES]],
    )


def validate(
    splunk: SplunkClient,
    index: str,
    sourcetype: str,
    manifest: dict,
    since: float,
    app: str,
    source: str | None = None,
    settings: dict[str, str] | None = None,
) -> Report:
    """source: one sample set among several sharing the sourcetype (an update's old and new).
    settings: the index-time settings under test, for the TIME_FORMAT check."""
    count = splunk.wait_stable(index, sourcetype, source=source)
    stable_at = time.time()
    timed = splunk.events_with_indextime(index, sourcetype, source)
    events = [(t, raw) for t, _, raw in timed]
    try:
        warnings: list[str] | None = splunk.parser_warnings(sourcetype, since, app, stable_at)
    except Exception:  # noqa: BLE001 - any failure of this check must fail the attempt
        warnings = None
    return Report(
        [
            check_count(count, manifest["event_count"], events),
            check_times(events, manifest["epochs"]),
            check_fallback(timed),
            check_warnings(warnings),
            check_time_format(settings, events),
        ]
    )


def regression(
    splunk: SplunkClient, index: str, sourcetype: str, manifest: dict, source: str | None = None
) -> Report:
    """Re-run the data-only index-time checks after a later stage changed search-time config."""
    timed = splunk.events_with_indextime(index, sourcetype, source)
    events = [(t, raw) for t, _, raw in timed]
    return Report(
        [
            check_count(len(events), manifest["event_count"], events),
            check_times(events, manifest["epochs"]),
        ]
    )
