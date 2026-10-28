import time

import pytest

from parsewright.tools.regex_test import test_regex as check_regex
from parsewright.tools.search_guard import MAX_ROWS, SearchRefused, build_search

ST = "acme:vpn__test_abcd1234_a1"


def test_base_search_is_fixed_and_capped():
    spl = build_search("pw_test", ST, "| stats count by user")
    assert spl.startswith(f"search index=pw_test sourcetype={ST} | stats count by user")
    assert spl.endswith(f"| head {MAX_ROWS}")


@pytest.mark.parametrize(
    "pipeline",
    [
        "| delete",
        "| collect index=main",
        "| dbxquery query=x",
        "| loadjob savedsearch=x",
        "| DELETE",  # case changes
        "| rest /services/apps/local",
        "| map search=x",
        "| tstats count where index=*",
        "| inputlookup x.csv",
        "| append [search index=main]",  # subsearch
        "| stats count `evil_macro`",  # macro
        "| nosuchcommand",
        "| search x | sendemail to=a@example.com",
        "index=main",  # not a pipeline: tries to replace the base search
        "OR index=main",
        "|",
    ],
)
def test_guard_refuses(pipeline):
    with pytest.raises((SearchRefused, ValueError)):
        build_search("pw_test", ST, pipeline)


def test_pipe_inside_quotes_is_not_a_command():
    spl = build_search("pw_test", ST, '| search msg="a | delete"')
    assert '| search msg="a | delete" | head 50' in spl


def test_guard_rejects_bad_index_or_sourcetype():
    with pytest.raises(ValueError):
        build_search("main", ST)
    with pytest.raises(ValueError):
        build_search("pw_test", "x OR index=main")


def test_regex_tool_reports_matches_and_groups():
    r = check_regex(r"user=(?<user>\w+)", ["user=alice ok", "user=bob", "none"])
    assert (r.valid, r.matched, r.lines) == (True, 2, 3)
    assert r.groups["user"] == ["alice", "bob"]


def test_regex_tool_times_out_instead_of_hanging():
    started = time.monotonic()
    r = check_regex(r"(a+)+$", ["a" * 5000 + "!"], timeout=0.2)
    assert r.timed_out and time.monotonic() - started < 5


def test_regex_tool_reports_invalid_patterns():
    assert not check_regex("(", ["x"]).valid


@pytest.mark.parametrize(
    "pipeline",
    [
        "| eval a=1 \\| delete",  # M1: escaped pipe outside quotes
        "| eval a=1 \\[search index=main\\]",  # escaped brackets outside quotes
        "| eval x='a\"b' | delete | eval y='c\"d'",  # single quotes hiding a pipe
        '| eval a=lookup("x", json_object("k","v"), json_array("f"))',  # M2: lookup()
        '| where like(x, "`evil`")',  # backtick even inside quotes
    ],
)
def test_guard_refuses_appsec_bypasses(pipeline):
    with pytest.raises(SearchRefused):
        build_search("pw_test", ST, pipeline)


def test_regex_timeout_is_one_total_budget():
    started = time.monotonic()
    check_regex(r"((\w+\s?)+)$", ["word " * 30 + "!"] * 200, timeout=0.5)
    assert time.monotonic() - started < 3
