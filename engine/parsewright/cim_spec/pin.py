"""Pin the CIM spec for the target models from the lab's Splunk_SA_CIM data model definitions.

Source of truth: the CIM add-on's own model JSON (fields' "recommended" flag and
"expected_values"), read over REST with the search token. The output is committed, so the
Validator never depends on a live lookup and the model never chooses required fields.
Run: python -m parsewright.cim_spec.pin
"""

import hashlib
import json
from pathlib import Path

from parsewright.config import Settings, load_env_file
from parsewright.tools.splunk_client import connect

MODELS = ("Authentication", "Network_Traffic", "Web")
OUT = Path(__file__).parent / "cim_spec.json"


def _fields(obj: dict) -> list[dict]:
    out = [*obj.get("fields", [])]
    for calc in obj.get("calculations", []):
        out.extend(calc.get("outputFields", []))
    return out


def pin_model(desc: dict) -> dict:
    datasets = {}
    for obj in desc["objects"]:
        fields = {}
        for f in _fields(obj):
            comment = f.get("comment") or {}
            if not isinstance(comment, dict):
                continue
            if comment.get("recommended") or comment.get("expected_values"):
                fields[f["fieldName"]] = {
                    "recommended": bool(comment.get("recommended")),
                    "expected_values": comment.get("expected_values", []),
                }
        datasets[obj["objectName"]] = {
            "parent": obj.get("parentName"),
            "constraints": [c.get("search", "") for c in obj.get("constraints", [])],
            "fields": dict(sorted(fields.items())),
        }
    return datasets


def main() -> None:
    load_env_file(Path(__file__).resolve().parents[3] / ".env")
    settings = Settings.from_env()
    svc = connect(settings, settings.splunk_search_token)
    app = json.loads(svc.get("apps/local/Splunk_SA_CIM", output_mode="json").body.read())
    spec: dict = {
        "source": "Splunk_SA_CIM data model definitions (datamodel/model REST endpoint)",
        "cim_version": app["entry"][0]["content"].get("version"),
        "models": {},
    }
    for model in MODELS:
        r = svc.get(
            f"datamodel/model/{model}", owner="nobody", app="Splunk_SA_CIM", output_mode="json"
        )
        desc = json.loads(json.loads(r.body.read())["entry"][0]["content"]["description"])
        spec["models"][model] = pin_model(desc)
    body = json.dumps(spec, indent=1, sort_keys=True)
    spec["sha256"] = hashlib.sha256(body.encode()).hexdigest()
    OUT.write_text(json.dumps(spec, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"pinned CIM {spec['cim_version']} for {', '.join(MODELS)} -> {OUT.name}")


if __name__ == "__main__":
    main()
