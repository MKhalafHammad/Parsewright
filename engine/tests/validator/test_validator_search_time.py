"""Extraction and CIM Validator tests on recorded-shape Splunk rows: no live Splunk."""

from parsewright.agents.profiler import FieldInfo, LogProfile
from parsewright.validator import cim, extraction


def manifest_of(events):
    return {"event_count": len(events), "epochs": [e["epoch"] for e in events], "events": events}


def ev(epoch, category, fields, cim_values):
    return {"epoch": epoch, "category": category, "fields": fields, "cim": cim_values}


PROFILE = LogProfile(
    format="kv",
    multiline=False,
    timestamp_example="",
    timestamp_format_candidates=[],
    timezone_in_timestamp=True,
    timezone_hint=None,
    vendor="acme",
    product="fw",
    sourcetype="acme:fw",
    event_categories=[],
    fields=[FieldInfo(name="src", coverage=1), FieldInfo(name="action", coverage=1)],
    cim_targets=["Network_Traffic"],
)
EVENTS = [
    ev(
        100,
        "network_traffic",
        {"src": "192.0.2.1", "action": "accept"},
        {"action": "allowed", "src": "192.0.2.1"},
    ),
    ev(
        200,
        "network_traffic",
        {"src": "192.0.2.2", "action": "drop"},
        {"action": "blocked", "src": "192.0.2.2"},
    ),
]


def rows(*pairs):
    return [{"t": str(t), **fields} for t, fields in pairs]


# --- extraction --------------------------------------------------------------------------


def test_extraction_passes_on_exact_values():
    r = extraction.validate(
        rows(
            (100, {"src": "192.0.2.1", "action": "accept"}),
            (200, {"src": "192.0.2.2", "action": "drop"}),
        ),
        manifest_of(EVENTS),
        PROFILE,
        set(),
    )
    assert r.passed


def test_greedy_regex_is_named():
    r = extraction.validate(
        rows(
            (100, {"src": "192.0.2.1 sport=5", "action": "accept"}),
            (200, {"src": "192.0.2.2", "action": "drop"}),
        ),
        manifest_of(EVENTS),
        PROFILE,
        set(),
    )
    values = r.checks[1]
    assert not values.passed and "1 greedy" in values.actual


def test_duplicate_values_are_caught():
    r = extraction.validate(
        rows(
            (100, {"src": ["192.0.2.1", "192.0.2.1"], "action": "accept"}),
            (200, {"src": "192.0.2.2", "action": "drop"}),
        ),
        manifest_of(EVENTS),
        PROFILE,
        set(),
    )
    assert not r.checks[2].passed and "src" in r.checks[2].actual


def test_missing_field_shows_in_coverage():
    r = extraction.validate(
        rows((100, {"src": "192.0.2.1"}), (200, {"src": "192.0.2.2"})),
        manifest_of(EVENTS),
        PROFILE,
        set(),
    )
    assert not r.checks[0].passed and "action: 0%" in r.checks[0].examples[0]


def test_fields_rewritten_by_cim_are_skipped_in_regression():
    r = extraction.validate(
        rows(
            (100, {"src": "192.0.2.1", "action": "allowed"}),
            (200, {"src": "192.0.2.2", "action": "blocked"}),
        ),
        manifest_of(EVENTS),
        PROFILE,
        {"action"},
    )
    assert r.passed


# --- CIM ---------------------------------------------------------------------------------


def nt(t, **f):
    return {"t": str(t), **{f"All_Traffic.{k}": v for k, v in f.items()}}


def test_cim_pass_and_three_numbers():
    report, scores = cim.validate(
        {
            "Network_Traffic": [
                nt(100, action="allowed", src="192.0.2.1"),
                nt(200, action="blocked", src="192.0.2.2"),
            ]
        },
        {"Network_Traffic": {"Allowed_Traffic": 1, "Blocked_Traffic": 1}},
        manifest_of(EVENTS),
    )
    assert report.passed
    s = scores[0]
    assert (s.passed, s.mapped, s.in_source) == (2, 2, 2)
    assert "dest" in s.not_in_source  # required by CIM, absent in this source: no penalty
    assert "required fields 2/2 passed" in s.line() and "not in source" in s.line()


def test_missing_required_cim_field_fails():
    report, scores = cim.validate(
        {
            "Network_Traffic": [
                nt(100, action="allowed", src="unknown"),
                nt(200, action="blocked", src="unknown"),
            ]
        },
        {"Network_Traffic": {"Allowed_Traffic": 1, "Blocked_Traffic": 1}},
        manifest_of(EVENTS),
    )
    assert not report.passed and scores[0].passed == 1 and scores[0].mapped == 1
    assert "src: 2 events wrong" in report.evidence()


def test_out_of_set_action_fails():
    report, _ = cim.validate(
        {
            "Network_Traffic": [
                nt(100, action="accept", src="192.0.2.1"),
                nt(200, action="drop", src="192.0.2.2"),
            ]
        },
        {"Network_Traffic": {}},
        manifest_of(EVENTS),
    )
    evidence = report.evidence()
    assert not report.passed and "action has values outside" in evidence and "'accept'" in evidence


def test_events_missing_from_the_model_fail():
    report, _ = cim.validate(
        {"Network_Traffic": [nt(100, action="allowed", src="192.0.2.1")]},
        {"Network_Traffic": {}},
        manifest_of(EVENTS),
    )
    assert (
        "FAILED Network_Traffic: events in the data model: expected 2, actual 1"
        in report.evidence()
    )


def test_built_in_fields_are_not_extraction_checks():
    prof = PROFILE.model_copy(
        update={"fields": [*PROFILE.fields, FieldInfo(name="host", coverage=1)]}
    )
    events = [
        ev(100, "network_traffic", {"src": "192.0.2.1", "action": "accept", "host": "fw01"}, {})
    ]
    r = extraction.validate(
        rows((100, {"src": "192.0.2.1", "action": "accept", "host": "parsewright-sample"})),
        manifest_of(events),
        prof,
        set(),
    )
    assert r.passed
