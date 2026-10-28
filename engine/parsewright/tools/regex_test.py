"""test_regex: try a regex on sample lines locally, with a timeout, before it reaches Splunk.

Python's `regex` differs from Splunk's PCRE in corner cases (R6), so this is a pre-check;
the Validator's run in Splunk stays the real proof.
"""

import time
from dataclasses import dataclass, field

import regex

TIMEOUT_S = 1.0  # total over all lines


@dataclass
class RegexResult:
    valid: bool
    matched: int = 0
    lines: int = 0
    timed_out: bool = False
    error: str = ""
    groups: dict[str, list[str]] = field(default_factory=dict)  # up to 3 values per group


def test_regex(pattern: str, lines: list[str], timeout: float = TIMEOUT_S) -> RegexResult:
    try:
        compiled = regex.compile(pattern)
    except regex.error as e:
        return RegexResult(valid=False, error=str(e), lines=len(lines))
    result = RegexResult(valid=True, lines=len(lines))
    deadline = time.monotonic() + timeout  # one budget for all lines, not per line
    for line in lines:
        try:
            match = compiled.search(line, timeout=max(0.01, deadline - time.monotonic()))
        except TimeoutError:
            result.timed_out = True
            result.error = "timed out (catastrophic backtracking)"
            return result
        if match:
            result.matched += 1
            for name, value in match.groupdict().items():
                values = result.groups.setdefault(name, [])
                if value is not None and len(values) < 3 and value not in values:
                    values.append(value)
    return result


test_regex.__test__ = False  # a tool, not a pytest test
