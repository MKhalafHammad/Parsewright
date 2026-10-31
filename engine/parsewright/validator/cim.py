"""CIM Validator: data model membership, required fields, allowed values, child datasets.

Scoring rule (design "CIM checks"): a field counts as missing only if the CIM expects it AND
the source has it. Three numbers per model: required fields passed, available fields mapped,
and fields not in the source (informational, no penalty).
"""

from collections import Counter
from dataclasses import dataclass

from parsewright import cim_spec
from parsewright.validator.index_time import MAX_EXAMPLES, Check, Report, _preview

UNMAPPED = {None, "", "unknown"}


@dataclass
class Score:
    model: str
    passed: int
    mapped: int
    in_source: int
    not_in_source: list[str]

    def line(self) -> str:
        missing = f" ({', '.join(self.not_in_source)})" if self.not_in_source else ""
        return (
            f"CIM {self.model}: required fields {self.passed}/{self.in_source} passed, "
            f"available fields mapped {self.mapped}/{self.in_source}, "
            f"not in source {len(self.not_in_source)}{missing}"
        )


def expected_by_model(manifest: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in manifest["events"]:
        model = cim_spec.CATEGORY_MODEL.get(e["category"])
        if model:
            out.setdefault(model, []).append(e)
    return out


def validate_model(
    model: str, rows: list[dict], child_counts: dict[str, int], truth: list[dict]
) -> tuple[list[Check], Score]:
    root = cim_spec.ROOT[model]
    by_t = {int(r["t"]): r for r in rows if "t" in r}

    def get(t: int, f: str):
        return by_t.get(t, {}).get(f"{root}.{f}")

    checks = [
        Check(
            f"{model}: events in the data model",
            len(by_t) == len(truth) and all(e["epoch"] in by_t for e in truth),
            str(len(truth)),
            str(len(by_t)),
            []
            if len(by_t) == len(truth)
            else ["events missing from the model: check the eventtype filter and tags"],
        )
    ]

    passed, mapped, wrong_examples = 0, 0, []
    in_source = [f for f in cim_spec.required(model) if any(f in e["cim"] for e in truth)]
    not_in_source = [f for f in cim_spec.required(model) if f not in in_source]
    for f in in_source:
        have_any = any(get(e["epoch"], f) not in UNMAPPED for e in truth if f in e["cim"])
        mapped += have_any
        bad = [e for e in truth if f in e["cim"] and get(e["epoch"], f) != e["cim"][f]]
        if not bad:
            passed += 1
        elif len(wrong_examples) < MAX_EXAMPLES:
            e = bad[0]
            wrong_examples.append(
                f"{f}: {len(bad)} events wrong, e.g. expected {e['cim'][f]!r}, "
                f"got {_preview(str(get(e['epoch'], f)))!r}"
            )
    checks.append(
        Check(
            f"{model}: required fields",
            passed == len(in_source),
            f"{len(in_source)} fields the source has, all correct",
            f"{passed}/{len(in_source)} correct",
            wrong_examples,
        )
    )

    constants = []
    for f in in_source:
        have = {get(e["epoch"], f) for e in truth if f in e["cim"]} - UNMAPPED
        want = {e["cim"][f] for e in truth if f in e["cim"]}
        if len(truth) >= 10 and len(have) == 1 and len(want) > 1:
            constants.append(
                f"{f} is always {next(iter(have))!r} but the source has {len(want)} values"
            )
    checks.append(
        Check(
            f"{model}: constant values",
            not constants,
            "no CIM field fixed to one value where the source varies",
            f"{len(constants)} constant fields" if constants else "none",
            constants[:MAX_EXAMPLES],
        )
    )

    out_of_set = []
    for f, allowed in cim_spec.expected_values(model).items():
        seen = Counter(v for t in by_t if (v := get(t, f)) not in UNMAPPED and v not in allowed)
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

    for dataset, f, value in cim_spec.CHILDREN[model]:
        want = sum(1 for e in truth if e["cim"].get(f) == value)
        have = child_counts.get(dataset, 0)
        checks.append(Check(f"{model}: {dataset}", have == want, str(want), str(have)))
    return checks, Score(model, passed, mapped, len(in_source), not_in_source)


def validate(
    rows_by_model: dict[str, list[dict]],
    children: dict[str, dict[str, int]],
    manifest: dict,
) -> tuple[Report, list[Score]]:
    checks, scores = [], []
    for model, truth in expected_by_model(manifest).items():
        c, s = validate_model(model, rows_by_model.get(model, []), children.get(model, {}), truth)
        checks += c
        scores.append(s)
    return Report(checks), scores
