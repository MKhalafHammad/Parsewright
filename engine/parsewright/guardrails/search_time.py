"""Search-time gate for the Extraction and CIM mapper agents (design "Config safety", T5.8).

Agents return structured proposals; this module turns them into .conf stanzas only after every
name, regex, expression and eventtype filter passes. Code, not the agent, picks stanza names,
transform names, eventtype anchors and tags.
"""

import re

from parsewright import cim_spec
from parsewright.guardrails.index_time import GuardrailBlock, backtracking_safe
from parsewright.tools.regex_test import test_regex

NAME = re.compile(r"[a-z][a-z0-9_]{0,39}")
FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
CORE = {"index", "host", "source", "sourcetype", "_time", "_raw", "eventtype", "tag", "linecount"}
KV_MODES = {"none", "auto", "json", "xml"}
DELIMS = {",", "\\t", "|", ";"}
# Eventtype filters: field comparisons only. No pipes, subsearches, macros, re-scoping, or
# backslashes (an escaped quote would desync our quote tracking from Splunk's and let a ) escape
# the sourcetype anchor).
FILTER_BLOCK = re.compile(
    r"[|\[\]`\\]|\b(index|sourcetype|source|host|eventtype|tag|splunk_server)\b", re.IGNORECASE
)
EVAL_BLOCK = re.compile(r"[|\[\]`]|\blookup\s*\(", re.IGNORECASE)
# CIM fields that may legitimately be a constant for one log source (design "Validator
# integrity"): every other CIM field must trace to an extracted field.
APPROVED_CONSTANTS = {"app", "vendor_product", "vendor", "product", "dvc"}
QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"')
IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
REGEX_META = set("\\[](){}.*+?|^$")
# Fields and functions that differ between the test and production (or over time): an EVAL
# reading them could pass validation and behave differently after promotion (appsec H2).
ENVIRONMENT = {
    "index",
    "sourcetype",
    "source",
    "host",
    "splunk_server",
    "eventtype",
    "tag",
    "linecount",
    "punct",
    "now",
    "time",
    "relative_time",
    "random",
    "_time",
    "_indextime",
}
IN_FIELD = re.compile(r"\s+in\s+\w+\s*$")
MAX_ITEMS = 20
LITERAL = re.compile(r'\s*("[^"]*"|\d+)\s*')


def _name(value: str, what: str) -> str:
    if not NAME.fullmatch(value):
        raise GuardrailBlock(f"{what} {value!r} must match ^[a-z][a-z0-9_]{{0,39}}$")
    return value


def _field(value: str, what: str) -> str:
    if not FIELD.fullmatch(value) or value in CORE:
        raise GuardrailBlock(f"{what} {value!r} is not an allowed field name")
    return value


# --- Extraction ------------------------------------------------------------------------------


def extraction(proposal, sourcetype: str, job: str, samples: list[str]) -> dict:
    """Return {"props": {...}, "transforms": {...}} search-time settings for the sourcetype."""
    if proposal.kv_mode not in KV_MODES:
        raise GuardrailBlock(f"KV_MODE must be one of {sorted(KV_MODES)}")
    props: dict[str, str] = {"KV_MODE": proposal.kv_mode}
    transforms: dict[str, dict[str, str]] = {}
    if len(proposal.extracts) > MAX_ITEMS:
        raise GuardrailBlock(f"at most {MAX_ITEMS} extracts")
    for ex in proposal.extracts:
        _name(ex.name, "extract name")
        if len(ex.regex) > 400:
            raise GuardrailBlock(f"EXTRACT-{ex.name} is longer than 400 characters")
        if IN_FIELD.search(ex.regex):  # "<regex> in <field>" applies it to another field
            raise GuardrailBlock(f"EXTRACT-{ex.name} may not end with 'in <field>'")
        result = test_regex(ex.regex, samples)
        if not result.valid:
            raise GuardrailBlock(f"EXTRACT-{ex.name} is not a valid regex: {result.error}")
        if result.timed_out:
            raise GuardrailBlock(f"EXTRACT-{ex.name} {result.error}")
        backtracking_safe(ex.regex, samples)
        groups = re.findall(r"\(\?P?<([A-Za-z_][A-Za-z0-9_]*)>", ex.regex)
        # Advisory only: (?<user>admi[n]) evades it; the Validator's per-event checks are the proof.
        for g, body in _group_bodies(ex.regex):
            if body and not set(body) & REGEX_META:
                raise GuardrailBlock(
                    f"EXTRACT-{ex.name} group {g} matches the literal text {body!r}, not a pattern"
                )
        if not groups:
            raise GuardrailBlock(f"EXTRACT-{ex.name} needs named groups (?<field>...)")
        for g in groups:
            _field(g, f"EXTRACT-{ex.name} group")
        if result.matched == 0:
            raise GuardrailBlock(f"EXTRACT-{ex.name} matches none of the sample events")
        props[f"EXTRACT-{ex.name}"] = ex.regex
    if proposal.delims is not None:
        d = proposal.delims
        if d.delimiter not in DELIMS:
            raise GuardrailBlock(f"DELIMS must be one of {sorted(DELIMS)}")
        if not d.fields or len(d.fields) > 60:
            raise GuardrailBlock("FIELDS must list 1 to 60 field names")
        for f in d.fields:
            _field(f, "FIELDS entry")
        name = f"parsewright_{job}_delims"
        transforms[name] = {
            "DELIMS": f'"{d.delimiter}"',
            "FIELDS": ", ".join(f'"{f}"' for f in d.fields),
        }
        props["REPORT-parsewright_delims"] = name
    return {"props": props, "transforms": transforms}


# --- CIM mapping -----------------------------------------------------------------------------


def _group_bodies(pattern: str) -> list[tuple[str, str]]:
    """(name, body) for each named group, with nested parentheses balanced."""
    out = []
    for m in re.finditer(r"\(\?P?<([A-Za-z_][A-Za-z0-9_]*)>", pattern):
        depth, i = 1, m.end()
        while i < len(pattern) and depth:
            if pattern[i] == "\\":
                i += 2
                continue
            depth += {"(": 1, ")": -1}.get(pattern[i], 0)
            i += 1
        out.append((m.group(1), pattern[m.end() : i - 1]))
    return out


def _references(expression: str) -> set[str]:
    """Field names an eval expression reads (quoted strings removed first)."""
    return set(IDENT.findall(QUOTED.sub(" ", expression)))


def cim(proposal, sourcetype: str, job: str, fields: set[str] | None = None) -> dict:
    """Return {"props": {...}, "eventtypes": {...}, "tags": {...}} for the sourcetype.

    fields: the extracted field names; when given, every CIM value must trace to one.
    """
    models = {et.model for et in proposal.eventtypes}
    known = set().union(*(cim_spec.known_fields(m) for m in models)) if models else set()
    props: dict[str, str] = {}
    if max(len(proposal.aliases), len(proposal.evals), len(proposal.eventtypes)) > MAX_ITEMS:
        raise GuardrailBlock(f"at most {MAX_ITEMS} aliases, evals and eventtypes each")
    for a in proposal.aliases:
        _field(a.field, "alias source")
        _field(a.cim_field, "alias target")
        if a.cim_field not in known:
            raise GuardrailBlock(f"{a.cim_field} is not a field of {sorted(models)}")
        if fields is not None and a.field not in fields:
            raise GuardrailBlock(f"alias source {a.field} is not an extracted field")
        props[f"FIELDALIAS-{a.cim_field}"] = f"{a.field} AS {a.cim_field}"
    for e in proposal.evals:
        _field(e.cim_field, "EVAL target")
        if e.cim_field not in known:
            raise GuardrailBlock(f"{e.cim_field} is not a field of {sorted(models)}")
        if not e.expression or len(e.expression) > 400 or EVAL_BLOCK.search(e.expression):
            raise GuardrailBlock(f"EVAL-{e.cim_field} expression is not allowed")
        env = {r.lower() for r in _references(e.expression)} & ENVIRONMENT
        if env or any(r.startswith("_") for r in _references(e.expression)):
            raise GuardrailBlock(
                f"EVAL-{e.cim_field} reads {sorted(env) or 'an internal field'}: a CIM value "
                "may not depend on where or when it runs"
            )
        if e.cim_field == "action" and LITERAL.fullmatch(e.expression):
            raise GuardrailBlock("EVAL-action may not be a constant: derive it from the event")
        if (
            fields is not None
            and e.cim_field not in APPROVED_CONSTANTS
            and not _references(e.expression) & fields
        ):
            raise GuardrailBlock(
                f"EVAL-{e.cim_field} does not read any extracted field: CIM values must trace "
                "to the source"
            )
        props[f"EVAL-{e.cim_field}"] = e.expression
    if not proposal.eventtypes:
        raise GuardrailBlock("at least one eventtype is required")
    eventtypes, tags = {}, {}
    for et in proposal.eventtypes:
        name = f"parsewright_{job}_{_name(et.name, 'eventtype name')}"
        flt = et.filter.strip()
        if len(flt) > 300 or FILTER_BLOCK.search(flt) or not _balanced(flt):
            raise GuardrailBlock(f"eventtype {et.name} filter is not allowed")
        # Anchored by code on the attempt's own sourcetype; the filter can only narrow it.
        eventtypes[name] = {"search": f"sourcetype={sourcetype}" + (f" ({flt})" if flt else "")}
        tags[f"eventtype={name}"] = {t: "enabled" for t in cim_spec.TAGS[et.model]}
    return {"props": props, "eventtypes": eventtypes, "tags": tags}


def _balanced(text: str) -> bool:
    depth, quoted = 0, False
    for ch in text:
        if ch == '"':
            quoted = not quoted
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not quoted
