"""The pinned CIM spec (cim_spec.json, written by pin.py from the lab's Splunk_SA_CIM).

Required fields are each root dataset's "recommended" fields; allowed values are the model's
"expected_values". The model never chooses either.
"""

import json
from functools import cache
from pathlib import Path

SPEC = Path(__file__).parent / "cim_spec.json"
ROOT = {"Authentication": "Authentication", "Network_Traffic": "All_Traffic", "Web": "Web"}
# Tags each model's root constraint searches for; eventtypes get these, chosen by code.
TAGS = {
    "Authentication": ["authentication"],
    "Network_Traffic": ["network", "communicate"],
    "Web": ["web", "proxy"],
}
# Child datasets checked against manifest truth: (dataset, CIM field, value).
CHILDREN = {
    "Authentication": [
        ("Failed_Authentication", "action", "failure"),
        ("Successful_Authentication", "action", "success"),
    ],
    "Network_Traffic": [
        ("Allowed_Traffic", "action", "allowed"),
        ("Blocked_Traffic", "action", "blocked"),
    ],
    "Web": [],
}
CATEGORY_MODEL = {
    "authentication": "Authentication",
    "network_traffic": "Network_Traffic",
    "web": "Web",
}


@cache
def spec() -> dict:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def root_fields(model: str) -> dict[str, dict]:
    return spec()["models"][model][ROOT[model]]["fields"]


def required(model: str) -> list[str]:
    return sorted(f for f, d in root_fields(model).items() if d["recommended"])


def expected_values(model: str) -> dict[str, list[str]]:
    # "0-254"-style ranges are documentation, not a value list.
    return {
        f: d["expected_values"]
        for f, d in root_fields(model).items()
        if d["expected_values"]
        and not any("-" in v and v[0].isdigit() for v in d["expected_values"])
    }


def known_fields(model: str) -> set[str]:
    return set(root_fields(model))


def summary(model: str) -> str:
    """Compact text for the CIM mapper's prompt."""
    vals = expected_values(model)
    lines = [f"{model} (root dataset {ROOT[model]}, tags {', '.join(TAGS[model])}):"]
    for f in sorted(known_fields(model)):
        rec = " (required)" if root_fields(model)[f]["recommended"] else ""
        allowed = f" allowed: {', '.join(vals[f])}" if f in vals and len(vals[f]) <= 12 else ""
        lines.append(f"  {f}{rec}{allowed}")
    return "\n".join(lines)
