"""The no-manifest Validator: what can be proven from the file and Splunk alone."""

import json

import pytest
from conftest import FIXTURES

from parsewright.agents.profiler import FieldInfo, LogProfile
from parsewright.validator import mechanical
from parsewright.validator.mechanical import (
    check_times_from_raw,
    check_zone,
    compare,
    expected_records,
    models_of,
    snapshot,
    validate_cim,
    validate_extraction,
)

TZ_SETTINGS = {
    "acme_fw": {"TIME_PREFIX": "ts=", "TIME_FORMAT": "%s%3N", "MAX_TIMESTAMP_LOOKAHEAD": "20"},
    "acme_fw_v2": {"TIME_PREFIX": "ts=", "MAX_TIMESTAMP_LOOKAHEAD": "30"},
    "acme_vpn": {
        "TIME_PREFIX": '"time":"',
        "TIME_FORMAT": "%Y-%m-%dT%H:%M:%S%:z",
        "MAX_TIMESTAMP_LOOKAHEAD": "32",
    },
    "acme_vpn_notz": {
        "TIME_PREFIX": '"time":"',
        "TIME_FORMAT": "%Y-%m-%d %H:%M:%S",
        "TZ": "Asia/Tokyo",
    },
    "acme_ssh": {"TIME_FORMAT": "%b %d %H:%M:%S", "TZ": "UTC", "MAX_TIMESTAMP_LOOKAHEAD": "15"},
    "acme_proxy": {"TIME_FORMAT": "%Y-%m-%dT%H:%M:%SZ", "TZ": "UTC"},
}
EXT = {
    "acme_fw": "log",
    "acme_fw_v2": "log",
    "acme_vpn": "json",
    "acme_vpn_notz": "json",
    "acme_ssh": "log",
    "acme_proxy": "csv",
}


def events_of(name: str, shift: int = 0) -> list[tuple[int, str]]:
    lines = [ln for ln in (FIXTURES / f"{name}.{EXT[name]}").read_text().splitlines() if ln]
    epochs = json.loads((FIXTURES / f"{name}.manifest.json").read_text())["epochs"]
    return [(e + shift, raw) for e, raw in zip(epochs, lines, strict=True)]


@pytest.mark.parametrize("name", list(TZ_SETTINGS))
def test_code_reads_every_fixture_timestamp_exactly_as_generated(name):
    """The time written in each line, read by code, equals the generator's truth: the check
    is as strict as a manifest for timestamps."""
    assert check_times_from_raw(events_of(name), TZ_SETTINGS[name]).passed


def test_a_wrong_timezone_shows_as_the_exact_offset():
    """Adversarial: Splunk applied TZ=UTC to local Tokyo times; nothing else would notice."""
    shifted = [(t - 32400, raw) for t, raw in events_of("acme_vpn_notz")]
    check = check_times_from_raw(shifted, TZ_SETTINGS["acme_vpn_notz"])
    assert not check.passed and "offset -32400 s" in check.actual


def test_a_timestamp_with_no_zone_and_no_tz_cannot_be_read():
    settings = {k: v for k, v in TZ_SETTINGS["acme_vpn_notz"].items() if k != "TZ"}
    check = check_times_from_raw(events_of("acme_vpn_notz"), settings)
    assert not check.passed and "set TZ" in check.actual


def test_the_confirmed_zone_is_enforced_only_where_timestamps_lack_one():
    notz = events_of("acme_vpn_notz")
    assert not check_zone(TZ_SETTINGS["acme_vpn_notz"] | {"TZ": "UTC"}, "Asia/Tokyo", notz).passed
    assert check_zone(TZ_SETTINGS["acme_vpn_notz"], "Asia/Tokyo", notz).passed
    # offsets in the text: no TZ needed, whatever the hint said
    assert check_zone(TZ_SETTINGS["acme_vpn"], "UTC", events_of("acme_vpn")).passed
    # no zone and nobody confirmed one: passes here, the run pauses for a human instead
    assert check_zone(TZ_SETTINGS["acme_vpn_notz"], None, notz).actual.startswith("no zone")


def test_records_are_counted_from_the_file():
    text = "a\n\nb\nc\n"
    assert expected_records(text, False, None) == 3
    multi = "2026-01-01 00:00:01 start\n  detail\n2026-01-01 00:00:02 next\n"
    settings = {"TIME_FORMAT": "%Y-%m-%d %H:%M:%S", "TZ": "UTC", "MAX_TIMESTAMP_LOOKAHEAD": "19"}
    assert expected_records(multi, True, settings) == 2


PROFILE = LogProfile(
    format="kv",
    multiline=False,
    timestamp_example="1",
    timestamp_format_candidates=["%s"],
    timezone_in_timestamp=True,
    timezone_hint=None,
    vendor="acme",
    product="fw",
    sourcetype="acme:fw",
    event_categories=["traffic"],
    fields=[
        FieldInfo(name="action", coverage=1.0),
        FieldInfo(name="src", coverage=1.0),
        FieldInfo(name="dport", coverage=1.0),
    ],
    cim_targets=["Network_Traffic"],
)
RAW = "ts=1 action=accept src=192.0.2.9 dport=53 note=x"


def row(**fields) -> dict:
    return {"t": "1", mechanical.RAW: RAW, **fields}


def test_exact_values_pass():
    rows = [row(action="accept", src="192.0.2.9", dport="53")]
    assert validate_extraction(rows, PROFILE, set()).passed


@pytest.mark.parametrize(
    "bad,why",
    [
        ({"src": "192.0.2.9 dport=53"}, "runs into another field"),  # greedy regex
        ({"src": "192.0.2.99"}, "not in its event"),  # invented value
        ({"action": "allowed"}, "not in its event"),  # a CIM value passed off as extracted
        ({"src": " 192.0.2.9"}, "not in its event"),  # untrimmed: not what the line says
    ],
)
def test_values_must_be_exactly_in_their_own_line(bad, why):
    """Adversarial: without a manifest, each value must still come from its own raw line."""
    fields = {"action": "accept", "src": "192.0.2.9", "dport": "53"} | bad
    report = validate_extraction([row(**fields)], PROFILE, set())
    assert not report.passed and why in report.evidence()


def test_missing_fields_fail_coverage():
    report = validate_extraction([row(action="accept")], PROFILE, set())
    assert not report.passed and "field coverage" in report.evidence()


def nt(**f) -> dict:
    return {"t": "1", **{f"All_Traffic.{k}": v for k, v in f.items()}}


GOOD = {
    "action": "allowed",
    "src": "192.0.2.9",
    "dest": "203.0.113.1",
    "dest_port": "53",
    "transport": "tcp",
    "bytes": "10",
    "src_port": "1",
    "rule": "r1",
    "dvc": "fw01",
}


def cim_report(rows, children=None, mapped=None, distinct=None):
    mapped = mapped or set(GOOD)
    allowed = sum(1 for r in rows if r.get("All_Traffic.action") == "allowed")
    blocked = sum(1 for r in rows if r.get("All_Traffic.action") == "blocked")
    children = children or {
        "Network_Traffic": {"Allowed_Traffic": allowed, "Blocked_Traffic": blocked}
    }
    return validate_cim({"Network_Traffic": rows}, children, mapped, distinct or {}, len(rows))


def test_a_good_mapping_passes():
    report, (score,) = cim_report([nt(**GOOD), nt(**GOOD | {"action": "blocked"})])
    assert report.passed and score.passed == score.in_source


@pytest.mark.parametrize(
    "rows,distinct,why",
    [
        ([nt(**GOOD | {"action": "deny"})], {}, "allowed values"),  # outside the CIM set
        ([nt(**GOOD | {"src": "unknown"})], {}, "required fields"),  # mapped but empty
        ([nt(**GOOD)] * 12, {"action": 2}, "constant values"),  # pinned while the source varies
    ],
)
def test_cim_gaming_is_caught_without_a_manifest(rows, distinct, why):
    """Adversarial: the same anti-gaming rules hold with no answer key."""
    report, _ = cim_report(rows, distinct=distinct)
    assert not report.passed and why in report.evidence()


def test_child_datasets_must_agree_with_the_actions():
    report, _ = cim_report(
        [nt(**GOOD)], children={"Network_Traffic": {"Allowed_Traffic": 0, "Blocked_Traffic": 1}}
    )
    assert not report.passed and "Allowed_Traffic" in report.evidence()


def test_models_come_from_the_tags_code_wrote():
    cim = {"tags": {"eventtype=x": {"network": "enabled", "communicate": "enabled"}}}
    assert models_of(cim) == ["Network_Traffic"]
    assert models_of({"tags": {}}) == []
    report, _ = validate_cim({}, {}, set(), {}, 10)
    assert not report.passed  # nothing tagged is never a pass


def test_updates_compare_with_productions_own_output_exactly():
    """Without a manifest, a registered version's samples must give what production gave,
    event for event (matched by content, so repeated timestamps are fine)."""
    rows = [{"t": "1", "src": "a"}, {"t": "1", "src": "b"}]
    models = {"Network_Traffic": [{"t": "1", "All_Traffic.src": "a"}]}
    base = snapshot([1, 1], rows, ["src"], models)
    assert compare(base, snapshot([1, 1], rows[::-1], ["src"], models), "cim").passed
    broken = snapshot([1, 1], [{"t": "1", "src": "a"}, {"t": "1"}], ["src"], models)
    report = compare(base, broken, "extraction")
    assert not report.passed and "same fields as production" in report.evidence()
    assert not compare(base, snapshot([1, 2], rows, ["src"], models), "index-time").passed


# --- CIM meaning guards (found in the lab: required fields filled with the wrong meaning) -----

from parsewright.validator.mechanical import check_directions, check_invented  # noqa: E402

LAB_PROPS = {  # what the CIM mapper proposed for a VPN log with no manifest
    "FIELDALIAS-dest_port": "dest_port AS dest_port",
    "FIELDALIAS-src_port": "dest_port AS src_port",
    "EVAL-bytes_in": "bytes_out",
    "FIELDALIAS-bytes_out": "bytes_out AS bytes_out",
    "EVAL-rule": 'if(proto=="tcp","vpn-access","other")',
    "EVAL-vendor_product": '"acme vpn"',
    "EVAL-action": 'case(verdict=="allow","allowed",verdict=="deny","blocked")',
}
EXTRACTED = {"dest_port", "bytes_out", "proto", "verdict", "user", "src_ip"}


def test_a_source_field_cannot_be_both_ends():
    """Adversarial: src_port and dest_port from the same field, bytes_in from bytes_out."""
    check = check_directions(LAB_PROPS, EXTRACTED)
    assert not check.passed
    assert "src_port and dest_port are both read from dest_port" in check.examples
    assert "bytes_in and bytes_out are both read from bytes_out" in check.examples
    good = {"FIELDALIAS-src": "src_ip AS src", "FIELDALIAS-dest_port": "dest_port AS dest_port"}
    assert check_directions(good, EXTRACTED).passed


def test_cim_values_must_come_from_the_event():
    """Adversarial: rule=vpn-access appears nowhere in the log. Allowed CIM values
    (action=blocked) and constant-by-design fields (vendor_product) are not invented."""
    raw = '{"verdict":"deny","proto":"tcp","dest_port":22,"bytes_out":251}'
    rows = [
        {
            mechanical.RAW: raw,
            "rule": "vpn-access",
            "action": "blocked",
            "vendor_product": "acme vpn",
            "dest_port": "22",
            "bytes_in": "251",
        }
    ]
    check = check_invented(rows, LAB_PROPS, ["Network_Traffic"])
    assert not check.passed and "invented values in rule" in check.actual
    honest = {k: v for k, v in LAB_PROPS.items() if k != "EVAL-rule"}
    assert check_invented(rows, honest, ["Network_Traffic"]).passed


def test_a_correct_constant_from_a_multi_source_eval_is_not_called_faked():
    """Lab regression: dest = gateway on every login is right, though the same EVAL reads
    dest_ip for sessions. Only single-source CIM fields get the constant check."""
    rows = [
        {
            "t": "1",
            "Authentication.dest": "vpn01.example.com",
            "Authentication.action": "success",
            "Authentication.user": "alice",
            "Authentication.src": "192.0.2.1",
            "Authentication.app": "vpn",
        }
    ] * 12
    report, _ = validate_cim(
        {"Authentication": rows},
        {"Authentication": {"Failed_Authentication": 0, "Successful_Authentication": 12}},
        {"dest", "action", "user", "src", "app"},
        {"dest": 0},
        12,
    )
    assert report.passed


# --- appsec review, Nov 2: each finding as an adversarial test ---------------------------------

from parsewright.validator.mechanical import (  # noqa: E402
    RECORD_START,
    UNCONFIRMED,
    bounded,
    example_has_zone,
    zone_needed,
)


@pytest.mark.parametrize("distinct", [{"action": 3}])
def test_a_faked_constant_action_fails_however_it_is_written(distinct):
    """H1: case(action=="accept","allowed",true(),"allowed") or an EVAL reading two fields:
    with source variety taken before the CIM layer, a pinned enumerated field is caught."""
    report, _ = cim_report([nt(**GOOD)] * 12, distinct=distinct)
    assert not report.passed and "constant values" in report.evidence()


def test_an_unstated_zone_fails_the_check_so_the_run_pauses():
    """H2: no zone in the timestamps and none stated is never a pass (the run turns this
    failure into a profile-review pause, for builds and parser updates alike)."""
    notz = events_of("acme_vpn_notz")
    check = check_zone(TZ_SETTINGS["acme_vpn_notz"], None, notz)
    assert not check.passed and check.actual == UNCONFIRMED
    assert mechanical.zone_unconfirmed(mechanical.Report([check]))


def test_an_extracted_field_already_named_src_counts_as_its_own_source():
    """M1: src extracted under its CIM name, then FIELDALIAS-dest = src AS dest."""
    check = check_directions({"FIELDALIAS-dest": "src AS dest"}, {"src"})
    assert not check.passed and "src and dest are both read from src" in check.examples


def test_merged_multi_line_records_are_counted_by_code_not_the_agent():
    """M3: a TIME_PREFIX that matches only some record starts cannot shrink the count."""
    text = "2026-01-01 00:00:01 a\n  x\n2026-01-01 00:00:02 b\n2026-01-01 00:00:03 c\n"
    narrow = {"TIME_PREFIX": "^2026-01-01 00:00:01", "TIME_FORMAT": "%Y", "TZ": "UTC"}
    assert expected_records(text, True, narrow) == 3
    assert RECORD_START.match("Oct  5 08:00:46 host sshd[1]: x")


def test_the_value_check_is_linear_and_bounded():
    """M5: 10k events x 60 fields must finish within the check's budget."""
    import time as _time

    names = [f"f{i}" for i in range(60)]
    prof = PROFILE.model_copy(update={"fields": [FieldInfo(name=n, coverage=1.0) for n in names]})
    raw = " ".join(f"{n}=v{i}" for i, n in enumerate(names))
    rows = [{"t": "1", mechanical.RAW: raw, **{n: f"v{i}" for i, n in enumerate(names)}}] * 2000
    start = _time.monotonic()
    validate_extraction(rows, prof, set())
    assert _time.monotonic() - start < 10


def test_values_must_be_whole_tokens_of_their_line():
    """M6: "1" or a truncated IP occurs inside longer tokens; it does not count."""
    raw = "src=192.0.2.9 user=admin1"
    assert bounded("192.0.2.9", raw) and not bounded("192.0.2", raw) and not bounded("1", raw)
    assert not bounded("admin", raw) and bounded("ADMIN1", raw, ignore_case=True)


def test_a_zone_on_some_lines_only_still_needs_a_stated_zone():
    """L1: every event is read, not only the first ones."""
    zoned = [(0, '{"time":"2026-10-20T08:00:46+00:00"}')] * 60
    bare = [(0, '{"time":"2026-10-20 17:00:46"}')]
    settings = {"TIME_PREFIX": '"time":"', "TIME_FORMAT": "%Y-%m-%dT%H:%M:%S%:z"}
    loose = {"TIME_PREFIX": '"time":"', "TIME_FORMAT": "%Y-%m-%d %H:%M:%S"}
    assert not zone_needed(zoned, settings)
    assert zone_needed(zoned + bare, loose)


@pytest.mark.parametrize("example", ["2026/10/11-22:14", "event XYZ", "Z"])
def test_only_a_real_zone_suffix_counts(example):
    """L3: a trailing Z or offset counts only right after the time digits."""
    assert not example_has_zone(example, f"x {example} y", profile_says=True)


def test_list_values_are_checked_element_by_element():
    """L5: mvappend(user, "root") cannot hide an invented value in a list."""
    raw = '{"user":"alice"}'
    rows = [{mechanical.RAW: raw, "user": ["alice", "root"]}]
    check = check_invented(rows, {"EVAL-user": 'mvappend(user,"root")'}, ["Authentication"])
    assert not check.passed and "user" in check.actual
