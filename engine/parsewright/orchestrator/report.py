"""The approval report's data, saved when a run passes (design "Platform and UI").

Raw events beside their parsed values, with highlight offsets computed here, so the UI only turns
(start, end, field) into React elements and never builds HTML from log text. Everything in it is
untrusted log text for the UI to render escaped.
"""

import tarfile

from parsewright.ta_builder.package import Package

MAX_EVENTS = 15
MAX_VALUE = 300
SKIP = {
    "t",
    "host",
    "source",
    "sourcetype",
    "index",
    "linecount",
    "punct",
    "splunk_server",
    "timestamp",
    "timeendpos",
    "timestartpos",
    "eventtype",
    "tag",
    "date_hour",
}


def _utf16(text: str, index: int) -> int:
    """A code-point index as a UTF-16 index: what the browser's String.slice counts."""
    return len(text[:index].encode("utf-16-le")) // 2


def highlights(raw: str, fields: dict[str, str]) -> list[dict]:
    """Non-overlapping spans where each extracted value appears in the raw line, in UTF-16
    offsets for the UI."""
    spans: list[dict] = []
    taken = [False] * len(raw)
    for name, value in sorted(fields.items(), key=lambda kv: -len(kv[1])):  # longest first
        if not value or len(value) > MAX_VALUE:
            continue
        start = raw.find(value)
        while start != -1 and any(taken[start : start + len(value)]):
            start = raw.find(value, start + 1)
        if start == -1:
            continue
        for i in range(start, start + len(value)):
            taken[i] = True
        spans.append(
            {"start": _utf16(raw, start), "end": _utf16(raw, start + len(value)), "field": name}
        )
    return sorted(spans, key=lambda s: s["start"])


def package_files(pkg: Package) -> dict[str, str]:
    """The .conf files exactly as installed (the approved package's own bytes)."""
    out = {}
    with tarfile.open(pkg.path) as tar:
        for m in tar.getmembers():
            if m.isfile() and m.name.endswith(".conf"):
                out[m.name.split("/", 1)[1]] = tar.extractfile(m).read().decode("utf-8")
    return out


def build(
    rows: list[dict],
    extracted: list[str],
    cim_props: dict[str, str],
    scores: list,
    pkg: Package,
    samples: int,
    total: int,
) -> dict:
    """rows: events with _raw and their parsed fields together (no join by time)."""
    shown = []
    for row in rows[:MAX_EVENTS]:
        raw = str(row.get("_raw", ""))[:2000]
        fields = {
            f: str(row[f])[:MAX_VALUE]
            for f in extracted
            if f not in SKIP and isinstance(row.get(f), str) and row.get(f)
        }
        shown.append(
            {
                "time": int(row.get("t", 0)),
                "raw": raw,
                "fields": fields,
                "highlights": highlights(raw, fields),
            }
        )
    first = rows[0] if rows else {}
    mapping = []
    for key, value in sorted(cim_props.items()):
        kind, cim_field = key.split("-", 1)
        source = value.split(" AS ")[0].strip() if kind == "FIELDALIAS" else value
        mapping.append(
            {
                "cim_field": cim_field,
                "kind": kind,
                "from": source,
                "example": str(first.get(cim_field, ""))[:MAX_VALUE],
            }
        )
    return {
        "events": shown,
        "mapping": mapping,
        "scores": [
            {
                "model": s.model,
                "passed": s.passed,
                "mapped": s.mapped,
                "in_source": s.in_source,
                "not_in_source": s.not_in_source,
                "line": s.line(),
            }
            for s in scores
        ],
        "confs": package_files(pkg),
        "holdout": {"learned_from": samples, "validated_on": total},
    }
