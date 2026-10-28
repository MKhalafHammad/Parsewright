import pytest

from parsewright.agents.cim_mapper import Alias, CimProposal, Eval, EventType
from parsewright.agents.extraction import Delims, Extract, ExtractionProposal
from parsewright.guardrails.index_time import GuardrailBlock
from parsewright.guardrails.search_time import cim, extraction

ST = "acme:ssh__test_abcd1234_a1"
JOB = "abcd1234"
SAMPLES = [
    "Oct 20 08:00:36 bastion01 sshd[8014]: Failed password for bob from 192.0.2.218 port 27237"
]


def ext(**kw):
    base = {"kv_mode": "none", "extracts": [], "delims": None, "rationale": ""}
    return ExtractionProposal.model_validate(base | kw)


def cimp(aliases=(), evals=(), eventtypes=None):
    ets = eventtypes or [EventType(name="ssh_auth", model="Authentication", filter="")]
    return CimProposal(aliases=list(aliases), evals=list(evals), eventtypes=ets, rationale="")


def test_extraction_builds_props_and_transforms():
    p = ext(
        extracts=[Extract(name="auth", regex=r"for (?<user>\S+) from (?<src>[\d.]+)")],
        delims=Delims(delimiter=",", fields=["a", "b"]),
    )
    out = extraction(p, ST, JOB, SAMPLES)
    assert out["props"]["EXTRACT-auth"].startswith("for (?<user>")
    assert out["props"]["REPORT-parsewright_delims"] == "parsewright_abcd1234_delims"
    assert out["transforms"]["parsewright_abcd1234_delims"]["FIELDS"] == '"a", "b"'


@pytest.mark.parametrize(
    ("proposal", "reason"),
    [
        (ext(extracts=[Extract(name="x", regex=r"(?<user>\S+)\n[script://x]")]), "match"),
        (ext(extracts=[Extract(name="x", regex=r"for (\S+)")]), "named groups"),
        (ext(extracts=[Extract(name="x", regex=r"(?<user>z{3}\d+)")]), "matches none"),
        (ext(extracts=[Extract(name="x", regex=r"(?<sourcetype>\S+)")]), "not an allowed field"),
        (ext(extracts=[Extract(name="X Y", regex=r"(?<user>\S+)")]), "must match"),
        (ext(extracts=[Extract(name="x", regex=r"(?<user>(a+)+)$")]), "slow|backtracking"),
        (ext(delims=Delims(delimiter="\n", fields=["a"])), "DELIMS"),
        (ext(delims=Delims(delimiter=",", fields=["a b"])), "not an allowed field"),
    ],
)
def test_extraction_blocks(proposal, reason):
    with pytest.raises(GuardrailBlock, match=reason):
        extraction(proposal, ST, JOB, SAMPLES)


def test_cim_eventtype_is_anchored_by_code_and_tagged_from_spec():
    p = cimp(
        aliases=[Alias(field="src_ip", cim_field="src")],
        evals=[Eval(cim_field="action", expression='if(outcome=="Accepted","success","failure")')],
        eventtypes=[
            EventType(
                name="ssh_auth",
                model="Authentication",
                filter='outcome="Accepted" OR outcome="Failed"',
            )
        ],
    )
    out = cim(p, ST, JOB)
    name = "parsewright_abcd1234_ssh_auth"
    assert out["eventtypes"][name]["search"] == (
        f'sourcetype={ST} (outcome="Accepted" OR outcome="Failed")'
    )
    assert out["tags"][f"eventtype={name}"] == {"authentication": "enabled"}
    assert out["props"]["FIELDALIAS-src"] == "src_ip AS src"


@pytest.mark.parametrize(
    ("proposal", "reason"),
    [
        # constant action: Validator gaming
        (cimp(evals=[Eval(cim_field="action", expression='"success"')]), "constant"),
        (cimp(evals=[Eval(cim_field="sourcetype", expression='"x"')]), "not an allowed field"),
        (cimp(evals=[Eval(cim_field="user", expression="[search index=main]")]), "not allowed"),
        (cimp(evals=[Eval(cim_field="user", expression="lookup(x)")]), "not allowed"),
        (cimp(aliases=[Alias(field="x", cim_field="not_a_cim_field")]), "not a field"),
        # eventtype filters may not re-scope, break out of the anchor, or pipe
        (cimp(eventtypes=[EventType(name="e", model="Web", filter="index=main")]), "filter"),
        (cimp(eventtypes=[EventType(name="e", model="Web", filter="sourcetype=*")]), "filter"),
        (cimp(eventtypes=[EventType(name="e", model="Web", filter="x=1) OR (y=2")]), "filter"),
        (cimp(eventtypes=[EventType(name="e", model="Web", filter="x=1 | delete")]), "filter"),
        (cimp(eventtypes=[EventType(name="e", model="Web", filter="tag=web")]), "filter"),
    ],
)
def test_cim_blocks(proposal, reason):
    with pytest.raises(GuardrailBlock, match=reason):
        cim(proposal, ST, JOB)


def test_cim_requires_an_eventtype():
    with pytest.raises(GuardrailBlock, match="eventtype"):
        cim(CimProposal(aliases=[], evals=[], eventtypes=[], rationale=""), ST, JOB)


# --- appsec Phase 3 findings -------------------------------------------------------------


def test_escaped_quote_cannot_break_the_eventtype_anchor():
    # H1: Splunk reads \" as a literal quote, so a ")" we think is quoted escapes the anchor.
    payload = 'type="\\"" ) OR ( type=* "\\""'
    p = cimp(eventtypes=[EventType(name="e", model="Authentication", filter=payload)])
    with pytest.raises(GuardrailBlock, match="filter"):
        cim(p, ST, JOB)


@pytest.mark.parametrize("group", ["_KEY_1", "_VAL_1", "_indextime", "_cd"])
def test_underscore_field_names_are_refused(group):
    # L1: _KEY_/_VAL_ take field names from log text, which could name index or host.
    p = ext(extracts=[Extract(name="x", regex=rf"(?<{group}>\w+)")])
    with pytest.raises(GuardrailBlock, match="not an allowed field"):
        extraction(p, ST, JOB, SAMPLES)


def test_long_regex_is_refused_before_it_runs():
    p = ext(extracts=[Extract(name="x", regex="(?<user>" + "a?" * 300 + ")")])
    with pytest.raises(GuardrailBlock, match="longer than 400"):
        extraction(p, ST, JOB, SAMPLES)


def test_extract_cannot_target_another_field():
    p = ext(extracts=[Extract(name="x", regex=r"(?<user>\S+) in sourcetype")])
    with pytest.raises(GuardrailBlock, match="in <field>"):
        extraction(p, ST, JOB, SAMPLES)


def test_item_counts_are_capped():
    many = [Extract(name=f"x{i}", regex=r"for (?<user>\S+)") for i in range(21)]
    with pytest.raises(GuardrailBlock, match="at most 20"):
        extraction(ext(extracts=many), ST, JOB, SAMPLES)
    evals = [Eval(cim_field="user", expression="lower(user)")] * 21
    with pytest.raises(GuardrailBlock, match="at most 20"):
        cim(cimp(evals=evals), ST, JOB)
