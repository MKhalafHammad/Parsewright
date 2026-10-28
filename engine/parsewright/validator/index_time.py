"""Index-time Validator: fixed checks, no AI (design "Validation design").

Ground truth is the generator's truth manifest: event count and the true epoch of each event.
"""

import re
import time
from collections import Counter
from dataclasses import dataclass, field

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
    splunk: SplunkClient, index: str, sourcetype: str, manifest: dict, since: float, app: str
) -> Report:
    count = splunk.wait_stable(index, sourcetype)
    stable_at = time.time()
    timed = splunk.events_with_indextime(index, sourcetype)
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
        ]
    )


def regression(splunk: SplunkClient, index: str, sourcetype: str, manifest: dict) -> Report:
    """Re-run the data-only index-time checks after a later stage changed search-time config."""
    timed = splunk.events_with_indextime(index, sourcetype)
    events = [(t, raw) for t, _, raw in timed]
    return Report(
        [
            check_count(len(events), manifest["event_count"], events),
            check_times(events, manifest["epochs"]),
        ]
    )
