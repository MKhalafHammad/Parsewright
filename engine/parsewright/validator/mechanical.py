"""Mechanical Validator: checks that need no answer key (design "Validation design").

A log with no truth manifest (any real log) is judged on what can be proven from the file and
from Splunk alone, on every event:

- index-time: one event per record of the file; each event's _time equals the time written in
  its own line, read here by code with the add-on's TIME_FORMAT and TZ (never by Splunk or AI);
- extraction: each value appears exactly in its own raw line and does not run into another
  field; every profile field is extracted at its stated coverage, once;
- CIM: events land in the data models the add-on tags; required fields the add-on maps are
  filled on every event, with allowed values; no CIM field is pinned to one value while its
  source field varies; child datasets agree with the action values;
- parser updates: a registered version's samples must give exactly what production gave them.

What it cannot prove is meaning (is it really UTC, is drop really blocked): the agents decide
that, and the approval report lists those decisions for the human who approves.
"""

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import regex

from parsewright import cim_spec
from parsewright.guardrails.search_time import APPROVED_CONSTANTS
from parsewright.validator.cim import UNMAPPED, Score
from parsewright.validator.index_time import (
    DIRECTIVE,
    DIRECTIVES,
    MAX_EXAMPLES,
    Check,
    Report,
    _preview,
)

MODE = "mechanical"
RAW = "pw_raw"  # the raw line, carried next to the fields (field_rows); never a log field name
MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
# Splunk directives as named groups, for reading a timestamp's parts back out of the raw text.
GROUPS = {
    "%Y": r"(?P<Y>\d{4})",
    "%y": r"(?P<y>\d{2})",
    "%m": r"(?P<m>\d{1,2})",
    "%d": r"(?P<d>\d{1,2})",
    "%e": r"\s?(?P<d>\d{1,2})",
    "%H": r"(?P<H>\d{1,2})",
    "%k": r"\s?(?P<H>\d{1,2})",
    "%I": r"(?P<I>\d{1,2})",
    "%l": r"\s?(?P<I>\d{1,2})",
    "%p": r"(?P<p>[AaPp][Mm])",
    "%M": r"(?P<M>\d{2})",
    "%S": r"(?P<S>\d{2})",
    "%b": r"(?P<b>[A-Za-z]{3})",
    "%h": r"(?P<b>[A-Za-z]{3})",
    "%B": r"(?P<b>[A-Za-z]{3})[A-Za-z]*",
    "%s": r"(?P<s>\d{9,10})",
    "%z": r"(?P<z>[+-]\d{2}:?\d{2}|Z)",
    "%:z": r"(?P<z>[+-]\d{2}:\d{2})",
    "%Z": r"(?P<Z>[A-Za-z][A-Za-z0-9+_/-]*)",
    "%T": r"(?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})",
    "%F": r"(?P<Y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})",
    "%D": r"(?P<m>\d{2})/(?P<d>\d{2})/(?P<y>\d{2})",
    "%R": r"(?P<H>\d{2}):(?P<M>\d{2})",
    "%r": r"(?P<I>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})\s+(?P<p>[AaPp][Mm])",
}
ISO = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,]\d+)?\s*(Z|[+-]\d{2}:?\d{2})?"
)
EPOCH = re.compile(r"(\d{10})(?:\.?\d{1,6})?(?!\d)")
CHECK_S = 2.0
RECORD_START = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|[A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2}|\d{10}\b"
)


def bounded(value: str, raw: str, ignore_case: bool = False) -> bool:
    """value occurs in raw as a whole token (not a piece of a longer one), or JSON-escaped."""
    flags = re.IGNORECASE if ignore_case else 0
    for v in (value, json.dumps(value)[1:-1]):
        if re.search(rf"(?<![\w.-]){re.escape(v)}(?![\w.-])", raw, flags):
            return True
    return False


def is_mechanical(manifest: dict) -> bool:
    return manifest.get("mode") == MODE


def manifest_for(text: str, name: str) -> dict:
    """The stand-in for a missing truth manifest: only what the file itself says."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return {
        "mode": MODE,
        "source": name,
        "event_count": len(lines),
        "epochs": [],
        "events": [],
        "multiline": False,  # the Run sets it from the confirmed profile
    }


# --- index-time ----------------------------------------------------------------------------


def _zone(text: str | None, tz: str | None):
    if text in (None, ""):
        if not tz:
            return None
        try:
            return ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            return None
    if text in ("Z", "UTC", "GMT"):
        return UTC
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", text)
    if not m:
        try:
            return ZoneInfo(text)
        except (ZoneInfoNotFoundError, ValueError):
            return None
    sign = 1 if m.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))


def _group_pattern(fmt: str) -> str | None:
    out, pos, seen = [], 0, set()
    for m in DIRECTIVE.finditer(fmt):
        out.append(re.sub(r"\\ ", r"\\s+", re.escape(fmt[pos : m.start()])))
        d = m.group(0)
        if d not in DIRECTIVES:
            return None
        group = GROUPS.get(d)
        if group:
            names = set(re.findall(r"\?P<(\w+)>", group))
            if names & seen:  # a part given twice: keep the first, match the rest plainly
                group = re.sub(r"\?P<\w+>", "?:", group)
            seen |= names
            out.append(group)
        else:  # subseconds, weekdays, %%: matched, not needed for whole seconds
            out.append(DIRECTIVES[d])
        pos = m.end()
    out.append(re.sub(r"\\ ", r"\\s+", re.escape(fmt[pos:])))
    return "".join(out)


def read_time(raw: str, settings: dict[str, str], year: int | None, deadline: float) -> int | None:
    """The event time written in `raw`, as epoch seconds, read with the add-on's own timestamp
    settings; None if it cannot be read. `year` fills in formats without one (syslog)."""
    import time

    prefix = settings.get("TIME_PREFIX")
    look = int(settings.get("MAX_TIMESTAMP_LOOKAHEAD") or 128)
    left = max(deadline - time.monotonic(), 0.001)
    start = 0
    if prefix:
        m = regex.search(prefix, raw, timeout=left)
        if m is None:
            return None
        start = m.end()
    window = raw[start : start + look]
    fmt = settings.get("TIME_FORMAT")
    tz = settings.get("TZ")
    if not fmt:  # Splunk's own recognition (pinned by TIME_PREFIX): epoch or ISO 8601 only
        w = window.lstrip()
        if e := EPOCH.match(w):
            return int(e.group(1))
        if i := ISO.match(w):
            zone = _zone(i.group(7), tz)
            if zone is None:
                return None
            parts = [int(x) for x in i.groups()[:6]]
            return int(datetime(*parts, tzinfo=zone).timestamp())
        return None
    pattern = _group_pattern(fmt)
    if pattern is None:
        return None
    if prefix:  # the timestamp starts where TIME_PREFIX ends
        m = regex.compile(r"\s*" + pattern).match(window, timeout=left)
    else:
        m = regex.compile(pattern).search(window, timeout=left)
    if m is None:
        return None
    g = {k: v for k, v in m.groupdict().items() if v is not None}
    if "s" in g:
        return int(g["s"])
    zone = _zone(g.get("z") or g.get("Z"), tz)
    if zone is None:
        return None
    month = int(g["m"]) if "m" in g else MONTHS.get(g.get("b", "").lower()[:3])
    hour = int(g.get("H", 0))
    if "I" in g:
        hour = int(g["I"]) % 12 + (12 if g.get("p", "").lower() == "pm" else 0)
    y = int(g["Y"]) if "Y" in g else (2000 + int(g["y"]) if "y" in g else year)
    if not (month and y and "d" in g):
        return None
    try:
        when = datetime(
            y, month, int(g["d"]), hour, int(g.get("M", 0)), int(g.get("S", 0)), tzinfo=zone
        )
    except ValueError:
        return None
    return int(when.timestamp())


def expected_records(text: str, multiline: bool, settings: dict[str, str] | None) -> int:
    """Records in the file: one per non-empty line, or for a multi-line log one per line that
    starts a record (a line whose timestamp can be read where TIME_PREFIX says)."""
    import time

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not multiline or not settings:
        return len(lines)
    deadline = time.monotonic() + CHECK_S
    by_agent = 0
    for ln in lines:
        if time.monotonic() > deadline:
            return len(lines)  # fail closed: every line a record
        try:
            by_agent += read_time(ln, settings, 2000, deadline) is not None
        except TimeoutError:
            return len(lines)
    # A detector the agent does not control: a prefix matching only some record starts must
    # not let merged records pass (appsec M3).
    by_code = sum(1 for ln in lines if RECORD_START.match(ln))
    return max(by_agent, by_code)


def check_times_from_raw(events: list[tuple[int, str]], settings: dict[str, str] | None) -> Check:
    """_time equals the time written in each event's own line (read by code)."""
    import time

    name = "timestamp accuracy"
    expected = "_time = the time written in the event, for every event"
    if not settings:
        return Check(name, False, expected, "no index-time settings to read the timestamps with")
    deadline = time.monotonic() + CHECK_S
    wrong, unread = [], []
    for t, raw in events:
        if time.monotonic() > deadline:
            return Check(name, False, expected, "check ran out of time: simplify the timestamp")
        year = datetime.fromtimestamp(t, UTC).year
        try:
            read = read_time(raw, settings, year, deadline)
            for other in (year - 1, year + 1):  # syslog without a year, across New Year
                if read is not None and read != t:
                    alt = read_time(raw, settings, other, deadline)
                    read = alt if alt == t else read
        except TimeoutError:
            read = None
        if read is None:
            unread.append(raw)
        elif read != t:
            wrong.append((t, read, raw))
    if unread:
        return Check(
            name,
            False,
            expected,
            f"{len(unread)} events whose timestamp cannot be read with TIME_PREFIX, "
            "TIME_FORMAT and TZ (set TZ when the timestamp has no zone)",
            [_preview(r) for r in unread[:MAX_EXAMPLES]],
        )
    if not wrong:
        return Check(name, True, expected, "all match")
    offset, n = Counter(t - r for t, r, _ in wrong).most_common(1)[0]
    return Check(
        name,
        False,
        expected,
        f"{len(wrong)}/{len(events)} events wrong; most common offset {offset:+d} s on {n} events",
        [f"_time={t} written={r} raw={_preview(raw)}" for t, r, raw in wrong[:MAX_EXAMPLES]],
    )


ZONED = re.compile(  # an epoch, or a zone right after a time of day (hh:mm[:ss][.fff])
    r"^\d{10}(?:\d{3}|\d{6}|\.\d{1,6})?$"
    r"|\d{2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\s?(?:Z|[+-]\d{2}:?\d{2}|UTC|GMT)$"
)


def example_has_zone(example: str, text: str, profile_says: bool) -> bool:
    """Whether a timestamp carries its own zone, read by code from the example: epoch times are
    UTC by definition, and a trailing Z or +hh:mm is a zone. The profile's own flag is used
    only if the example is not really in the file (the model may misquote it)."""
    example = example.strip()
    if not example or example not in text:
        return profile_says
    return bool(ZONED.search(example))


def zone_needed(events: list[tuple[int, str]], settings: dict[str, str] | None) -> bool:
    """Whether any event's time can be read only with TZ: its timestamp carries no zone."""
    import time

    bare = {k: v for k, v in (settings or {}).items() if k != "TZ"}
    deadline = time.monotonic() + CHECK_S
    for _, raw in events:  # every event: a mixed log may carry a zone only on some lines
        if time.monotonic() > deadline:
            return True  # could not prove a zone everywhere: a human states it
        try:
            if read_time(raw, bare, 2000, deadline) is None:
                return True
        except TimeoutError:
            return True
    return False


UNCONFIRMED = "no zone in the timestamps and none stated: a human must state it"


def zone_unconfirmed(report) -> bool:
    """The run's cue to pause for a human (profile review) instead of retrying the agent."""
    return any(c.name == "timezone" and c.actual == UNCONFIRMED for c in report.checks)


def check_zone(
    settings: dict[str, str] | None, confirmed_tz: str | None, events: list[tuple[int, str]]
) -> Check:
    """A timestamp without a zone needs the timezone a human confirmed, not a guess. Unconfirmed,
    this passes and the run pauses for a human instead (Run.zone_unconfirmed)."""
    name, expected = "timezone", "TZ is the confirmed timezone when timestamps carry none"
    if not zone_needed(events, settings):
        return Check(name, True, expected, "timestamps carry their own zone")
    if not confirmed_tz:
        return Check(name, False, expected, UNCONFIRMED)
    tz = (settings or {}).get("TZ")
    if tz == confirmed_tz:
        return Check(name, True, expected, f"TZ = {tz} (confirmed)")
    return Check(name, False, expected, f"TZ is {tz!r}; the confirmed timezone is {confirmed_tz}")


# --- extraction ----------------------------------------------------------------------------


def validate_extraction(rows: list[dict], profile, skip: set[str]) -> Report:
    from parsewright.validator.extraction import BUILT_IN, duplicates

    names = [f.name for f in profile.fields if f.name not in skip and f.name not in BUILT_IN]
    stated = {f.name: f.coverage for f in profile.fields}
    events = [(int(r.get("t", 0)), r) for r in rows]
    n = max(len(events), 1)
    short = []
    for f in names:
        have = sum(1 for _, r in events if r.get(f) not in (None, "", [])) / n
        if have < 0.9 * stated[f]:
            short.append(f"{f}: {have:.0%} of events, expected about {stated[f]:.0%}")
    coverage = Check(
        "field coverage",
        not short,
        "every profile field at its stated coverage",
        f"{len(short)} fields short" if short else "all fields covered",
        short[:MAX_EXAMPLES],
    )
    import time

    missing, greedy = [], []
    others = {  # one compiled pattern per field: "another field's key=" inside a value
        f: re.compile(
            "|".join(
                rf'(?:^|[\s,;|{{]){re.escape(o)}\s*[=:]|"{re.escape(o)}":' for o in names if o != f
            )
            or r"(?!x)x"
        )
        for f in names
    }
    deadline = time.monotonic() + 4 * CHECK_S
    for _, r in events:
        if time.monotonic() > deadline:
            missing.append("check ran out of time: too many events or fields to verify")
            break
        raw = str(r.get(RAW, ""))
        for f in names:
            vals = r.get(f)
            for v in vals if isinstance(vals, list) else [vals]:
                if not isinstance(v, str) or not v:
                    continue
                if not bounded(v, raw):
                    missing.append(f"{f}: {_preview(v)!r} is not in its event: {_preview(raw)}")
                elif v != v.strip() or others[f].search(v):
                    greedy.append(f"{f}: {_preview(v)!r} runs into another field: {_preview(raw)}")
    values = Check(
        "field values",
        not missing and not greedy,
        "every value appears exactly in its own event and stops at the next field",
        f"{len(missing)} values not in their event, {len(greedy)} running into another field"
        if missing or greedy
        else "all values exact",
        (missing + greedy)[:MAX_EXAMPLES],
    )
    return Report([coverage, values, duplicates(events, names)])


# --- CIM -----------------------------------------------------------------------------------


def models_of(cim: dict) -> list[str]:
    """The data models the add-on's tags select (code chose the tags from cim_spec)."""
    tags = {t for s in cim.get("tags", {}).values() for t in s}
    return [m for m, need in cim_spec.TAGS.items() if set(need) <= tags]


def validate_cim(
    rows_by_model: dict[str, list[dict]],
    children: dict[str, dict[str, int]],
    mapped: set[str],
    source_distinct: dict[str, int],
    total: int,
) -> tuple[Report, list[Score]]:
    """mapped: CIM fields the add-on writes (aliases, evals) or that exist under the CIM name;
    source_distinct: distinct values of the source field behind each mapped CIM field."""
    checks, scores = [], []
    for model, rows in rows_by_model.items():
        root = cim_spec.ROOT[model]

        def get(r: dict, f: str, root=root):
            return r.get(f"{root}.{f}")

        checks.append(
            Check(
                f"{model}: events in the data model",
                bool(rows),
                "at least one event",
                f"{len(rows)} of {total} events",
                [] if rows else ["no event reached the model: check the eventtype filter and tags"],
            )
        )
        required = cim_spec.required(model)
        ours = [f for f in required if f in mapped]
        passed, empty = 0, []
        for f in ours:
            bad = [r for r in rows if get(r, f) in UNMAPPED]
            if not bad:
                passed += 1
            elif len(empty) < MAX_EXAMPLES:
                empty.append(f"{f}: empty or 'unknown' on {len(bad)} of {len(rows)} events")
        checks.append(
            Check(
                f"{model}: required fields",
                passed == len(ours),
                f"{len(ours)} mapped required fields filled on every event",
                f"{passed}/{len(ours)} filled",
                empty,
            )
        )
        out_of_set = []
        for f, allowed in cim_spec.expected_values(model).items():
            seen = Counter(v for r in rows if (v := get(r, f)) not in UNMAPPED and v not in allowed)
            if seen:
                vals = ", ".join(f"{v!r} x{n}" for v, n in seen.most_common(3))
                out_of_set.append(f"{f} has values outside {allowed[:8]}: {vals}")
        checks.append(
            Check(
                f"{model}: allowed values",
                not out_of_set,
                "0 out-of-set values",
                f"{len(out_of_set)} fields with out-of-set values" if out_of_set else "0",
                out_of_set[:MAX_EXAMPLES],
            )
        )
        constants = []
        for f in ours:
            have = {get(r, f) for r in rows} - UNMAPPED
            if len(rows) >= 10 and len(have) == 1 and source_distinct.get(f, 1) > 1:
                constants.append(
                    f"{f} is always {next(iter(have))!r} but its source field has "
                    f"{source_distinct[f]} values"
                )
        checks.append(
            Check(
                f"{model}: constant values",
                not constants,
                "no CIM field fixed to one value where its source varies",
                f"{len(constants)} constant fields" if constants else "none",
                constants[:MAX_EXAMPLES],
            )
        )
        for dataset, f, value in cim_spec.CHILDREN[model]:
            want = sum(1 for r in rows if get(r, f) == value)
            have = children.get(model, {}).get(dataset, 0)
            checks.append(Check(f"{model}: {dataset}", have == want, str(want), str(have)))
        not_ours = [f for f in required if f not in mapped]
        scores.append(Score(model, passed, passed, len(ours), not_ours))
    if not rows_by_model:
        checks.append(
            Check("CIM data models", False, "at least one model tagged", "no model tagged")
        )
    return Report(checks), scores


# --- parser updates: production's own output is the answer key -------------------------------


def snapshot(
    times: list[int], field_rows: list[dict], names: list[str], model_rows: dict[str, list[dict]]
) -> dict:
    """What production gives a registered sample set, in a form compared as multisets (events
    are matched by content, so repeated timestamps are fine)."""

    def fields(r: dict) -> tuple:
        return tuple(sorted((f, str(r[f])) for f in names if r.get(f) not in (None, "", [])))

    return {
        "times": sorted(times),
        "fields": sorted(map(list, map(fields, field_rows))),
        "models": {
            m: sorted(
                sorted((k, str(v)) for k, v in r.items() if k != "t" and v not in (None, ""))
                for r in rows
            )
            for m, rows in model_rows.items()
        },
    }


def compare(baseline: dict, now: dict, stage: str) -> Report:
    """Exact equality with production's output, per stage's part of the snapshot."""

    def diff(a: list, b: list) -> tuple[int, list]:
        ca, cb = Counter(map(json.dumps, a)), Counter(map(json.dumps, b))
        gone = list((ca - cb).elements())
        return len(gone) + sum((cb - ca).values()), gone[:MAX_EXAMPLES]

    checks = []
    n, ex = diff(baseline["times"], now["times"])
    checks.append(
        Check(
            "same timestamps as production",
            n == 0,
            "0 differences",
            f"{n} differences",
            [f"production had {e}" for e in ex],
        )
    )
    if stage in ("extraction", "cim"):
        n, ex = diff(baseline["fields"], now["fields"])
        checks.append(
            Check(
                "same fields as production",
                n == 0,
                "0 differences",
                f"{n} events differ",
                [f"production gave {_preview(e)}" for e in ex],
            )
        )
    if stage == "cim":
        for m in sorted(set(baseline["models"]) | set(now["models"])):
            n, ex = diff(baseline["models"].get(m, []), now["models"].get(m, []))
            checks.append(
                Check(
                    f"{m}: same CIM values as production",
                    n == 0,
                    "0 differences",
                    f"{n} events differ",
                    [f"production gave {_preview(e)}" for e in ex],
                )
            )
    return Report(checks)


# --- CIM meaning guards (both modes: a manifest only covers the fields it lists) -------------

# CIM fields that are legitimately the same value for a whole sourcetype (set by an EVAL).
CONSTANT_OK = APPROVED_CONSTANTS  # the guardrail's own list: one source of truth
# CIM fields that describe opposite ends: one source field can never be both.
OPPOSITE = [
    ("src", "dest"),
    ("src_ip", "dest_ip"),
    ("src_port", "dest_port"),
    ("src_mac", "dest_mac"),
    ("src_user", "user"),
    ("bytes_in", "bytes_out"),
    ("packets_in", "packets_out"),
]


def cim_sources(cim_props: dict[str, str], extracted: set[str]) -> dict[str, set[str]]:
    """Which extracted fields each CIM field the add-on writes is read from."""
    from parsewright.guardrails.search_time import _references

    out: dict[str, set[str]] = {}
    for key, value in cim_props.items():
        if key.startswith("FIELDALIAS-"):
            src, _, dest = value.partition(" AS ")
            out.setdefault(dest.strip(), set()).add(src.strip())
        elif key.startswith("EVAL-"):
            out.setdefault(key.split("-", 1)[1], set()).update(_references(value) & extracted)
    return out


def check_directions(cim_props: dict[str, str], extracted: set[str]) -> Check:
    """A source field cannot be both ends: src_port and dest_port both from dest_port is a
    required field filled with the wrong meaning (found in the lab)."""
    sources = cim_sources(cim_props, extracted)
    for pair in OPPOSITE:  # an extracted field already named src/dest is its own source
        for f in pair:
            if f not in sources and f in extracted:
                sources[f] = {f}
    clashes = []
    for a, b in OPPOSITE:
        shared = sources.get(a, set()) & sources.get(b, set())
        if a in sources and b in sources and shared and a != b:
            clashes.append(f"{a} and {b} are both read from {', '.join(sorted(shared))}")
    return Check(
        "CIM directions",
        not clashes,
        "no source field mapped to both ends (src/dest, in/out)",
        f"{len(clashes)} clashes" if clashes else "none",
        clashes[:MAX_EXAMPLES],
    )


def check_invented(rows: list[dict], cim_props: dict[str, str], models: list[str]) -> Check:
    """Every value the add-on writes into a CIM field comes from its own event: it appears in
    the raw line, or it is one of the field's allowed CIM values (action=blocked), or the field
    is one that is constant by design (vendor_product). Otherwise it was invented."""
    allowed: dict[str, set[str]] = {}
    for m in models:
        for f, vals in cim_spec.expected_values(m).items():
            allowed.setdefault(f, set()).update(v.lower() for v in vals)
    targets = sorted(cim_sources(cim_props, set()).keys())
    invented: Counter = Counter()
    example: dict[str, str] = {}
    for r in rows:
        raw = str(r.get(RAW, ""))
        for f in targets:
            vals = r.get(f)
            for v in vals if isinstance(vals, list) else [vals]:
                if f in CONSTANT_OK or not isinstance(v, str) or v in UNMAPPED:
                    continue
                if v.lower() in allowed.get(f, ()) or bounded(v, raw, ignore_case=True):
                    continue
                invented[f] += 1
                example.setdefault(f, f"{f}={_preview(v)!r} does not occur in: {_preview(raw)}")
    return Check(
        "CIM values from the event",
        not invented,
        "every CIM value appears in its event or is an allowed CIM value",
        f"{sum(invented.values())} invented values in {', '.join(sorted(invented))}"
        if invented
        else "all traced to their event",
        [example[f] for f in sorted(invented)][:MAX_EXAMPLES],
    )
