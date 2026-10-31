"""Extraction Validator: field coverage, values, greedy regexes and duplicates (no AI).

Events are joined to the truth manifest by epoch (unique per event by construction). Fields the
manifest knows by name are checked value by value on every event, including the holdout events
the agent never saw; fields only the profile names are checked for coverage.
"""

from parsewright.agents.profiler import LogProfile
from parsewright.validator.index_time import MAX_EXAMPLES, Check, Report, _preview

BUILT_IN = {"host", "source", "sourcetype", "index", "splunk_server", "linecount", "punct"}


def _value(row: dict, field: str) -> str | list | None:
    value = row.get(field)
    return None if value in (None, "", []) else value


def validate(rows: list[dict], manifest: dict, profile: LogProfile, skip: set[str]) -> Report:
    """skip: fields a later stage deliberately rewrites (EVAL/FIELDALIAS targets)."""
    truth = {e["epoch"]: e["fields"] for e in manifest["events"]}
    by_t = {int(r["t"]): r for r in rows if "t" in r}
    events = [(t, by_t.get(t, {})) for t in truth]
    known = {f for fields in truth.values() for f in fields}
    # Splunk's built-in fields are set at ingest, not extracted (and the gate forbids
    # overwriting them), so they are never extraction checks.
    names = [f.name for f in profile.fields if f.name not in skip and f.name not in BUILT_IN]
    return Report(
        [
            coverage(events, truth, profile, names, known),
            values(events, truth, [f for f in names if f in known]),
            duplicates(events, names),
        ]
    )


def coverage(events, truth, profile: LogProfile, names: list[str], known: set[str]) -> Check:
    stated = {f.name: f.coverage for f in profile.fields}
    short = []
    for f in names:
        have = sum(1 for _, row in events if _value(row, f) is not None) / max(len(events), 1)
        if f in known:
            want = sum(1 for t, _ in events if f in truth[t]) / max(len(events), 1)
            ok = have >= want - 0.02
        else:
            want = stated[f]
            ok = have >= 0.9 * want
        if not ok:
            short.append(f"{f}: {have:.0%} of events, expected {want:.0%}")
    return Check(
        "field coverage",
        not short,
        "every profile field at its expected coverage",
        f"{len(short)} fields short" if short else "all fields covered",
        short[:MAX_EXAMPLES],
    )


def values(events, truth, fields: list[str]) -> Check:
    wrong, greedy, examples = 0, 0, []
    for t, row in events:
        for f in fields:
            if f not in truth[t]:
                continue
            want, have = truth[t][f], _value(row, f)
            if isinstance(have, list) or have == want:
                continue
            wrong += 1
            if isinstance(have, str) and have.startswith(want) and len(have) > len(want):
                greedy += 1
            if len(examples) < MAX_EXAMPLES:
                examples.append(
                    f"{f}: expected {_preview(want)!r}, extracted {_preview(str(have))!r}"
                )
    actual = f"{wrong} wrong values" + (
        f" ({greedy} greedy: value runs past the field)" if greedy else ""
    )
    return Check("field values", wrong == 0, "every value equals the source", actual, examples)


def duplicates(events, names: list[str]) -> Check:
    dup = sorted({f for _, row in events for f in names if isinstance(row.get(f), list)})
    return Check(
        "duplicates",
        not dup,
        "single-valued fields have one value",
        f"multi-valued: {', '.join(dup)}" if dup else "none",
        [
            f"{f} extracted more than once per event (two extractions or KV_MODE plus a regex)"
            for f in dup[:MAX_EXAMPLES]
        ],
    )
