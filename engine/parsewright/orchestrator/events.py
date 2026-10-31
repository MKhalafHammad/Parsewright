"""Structured log events: every ledger "log" event carries its stage, attempt, actor and kind.

The orchestrator writes one text line per event (the CLI prints it unchanged) plus metadata the
web UI reads instead of pattern-matching the text. The metadata is data only: it never drives a
transition. A plain line callable (`print`, `list.append`) still works: `sink` wraps it so it
receives the line alone.
"""

import json
from collections.abc import Callable

STAGES = frozenset(
    {"profile", "index-time", "extraction", "cim", "diagnose", "regression", "promotion"}
)
ACTORS = frozenset(
    {
        "profiler",
        "router",
        "index_time",
        "extraction",
        "cim_mapper",
        "drift_analyst",
        "gate",
        "orchestrator",
        "validator",
        "human",
    }
)
KINDS = frozenset(
    {
        "start",
        "proposal",
        "guardrail_block",
        "deploy",
        "ingest",
        "check_pass",
        "check_fail",
        "evidence",
        "backtrack",
        "human_wait",
        "human_action",
        "budget",
        "info",
    }
)
FIELDS = ("stage", "attempt", "visit", "actor", "kind", "detail")
LINE_CAP = 2000  # per physical line, as before
TEXT_CAP = 20_000  # a whole multi-line event (one Validator report)
DETAIL_CAP = 20_000


def meta(
    kind: str,
    actor: str,
    stage: str | None = None,
    attempt: int | None = None,
    visit: int | None = None,
    detail: dict | None = None,
) -> dict:
    """The metadata of one event. Unknown values are a programming error, refused here."""
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}")
    if actor not in ACTORS:
        raise ValueError(f"unknown event actor {actor!r}")
    if stage is not None and stage not in STAGES:
        raise ValueError(f"unknown event stage {stage!r}")
    return {
        "stage": stage,
        "attempt": attempt,
        "visit": visit,
        "actor": actor,
        "kind": kind,
        "detail": detail or {},
    }


def normalize(m: dict | None) -> dict:
    """All six fields, always: a line emitted without metadata is a run-level orchestrator
    info event. detail is made JSON-safe and replaced by {"truncated": true} if too large."""
    m = m or {}
    out = {
        "stage": m.get("stage"),
        "attempt": m.get("attempt"),
        "visit": m.get("visit"),
        "actor": m.get("actor") or "orchestrator",
        "kind": m.get("kind") or "info",
    }
    text = json.dumps(m.get("detail") or {}, default=str)
    out["detail"] = {"truncated": True} if len(text) > DETAIL_CAP else json.loads(text)
    return out


def cap_line(line: str) -> str:
    return "\n".join(part[:LINE_CAP] for part in line.split("\n"))[:TEXT_CAP]


def record(line: str, m: dict | None = None) -> dict:
    """The ledger data of one log event."""
    return {"line": cap_line(line), **normalize(m)}


class Structured:
    """An output callback that takes (line, meta). Anything else is treated as line-only."""

    def __init__(self, fn: Callable[[str, dict | None], None]):
        self.fn = fn

    def __call__(self, line: str, meta: dict | None = None) -> None:
        self.fn(line, meta)


def sink(out: Callable[..., None]) -> Structured:
    """`out` as a (line, meta) callback: a plain callable such as `print` gets only the line."""
    if isinstance(out, Structured):
        return out
    return Structured(lambda line, meta=None: out(line))
