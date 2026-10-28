"""Final gate over the complete add-on, run by code just before every package build.

The per-stage gates check what an agent proposed; this one checks what will actually be written,
so a bug or a gap in a stage gate cannot ship a forbidden setting (defence in depth). Keys are
matched after Unicode normalisation (NFKC) and case-folding; anything not on an allowlist is
refused, so lookalike characters and new spellings fail closed.
"""

import re
import unicodedata

from parsewright import cim_spec
from parsewright.guardrails import search_time
from parsewright.guardrails.index_time import ALLOWED as INDEX_TIME
from parsewright.guardrails.index_time import GuardrailBlock
from parsewright.ta_builder.naming import require_sourcetype

CONF_FILES = {"props", "transforms", "eventtypes", "tags"}
# props keys: exact index-time keys plus search-time class prefixes. Nothing else.
PROPS_EXACT = {k.upper() for k in INDEX_TIME} | {"KV_MODE"}
PROPS_PREFIXES = ("EXTRACT-", "REPORT-", "FIELDALIAS-", "EVAL-")
TRANSFORM_KEYS = {"DELIMS", "FIELDS"}  # the only transform keys any stage generates
# Named only for clearer block reasons; the allowlists above already refuse them.
FORBIDDEN = re.compile(
    r"^(TRANSFORMS-|SEDCMD-|LOOKUP-|INGEST_EVAL|DEST_KEY|WRITE_META|_TCP_ROUTING|_SYSLOG_ROUTING"
    r"|_METADATA|CLONE_SOURCETYPE|SOURCE_KEY|UNARCHIVE_CMD|INVALID_CAUSE|NO_BINARY_CHECK"
    r"|PREAMBLE_REGEX|FIELD_HEADER_REGEX|INDEXED_EXTRACTIONS)",
    re.IGNORECASE,
)
FORMAT_BLOCK = re.compile(r"_meta|metadata|queue|nullqueue|_tcp_routing", re.IGNORECASE)
CORE_TARGETS = search_time.CORE
ALIAS_TARGETS = re.compile(r"\bAS(?:NEW)?\s+(\S+)", re.IGNORECASE)


def norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).strip()


def _key(key: str, where: str) -> str:
    k = norm(key)
    if k != key or not k.isascii():
        raise GuardrailBlock(f"{where}: key {key!r} has hidden or non-ASCII characters")
    return k.upper()


def check(confs: dict[str, dict[str, dict[str, str]]], job: str, sourcetype: str) -> None:
    """Raise GuardrailBlock unless every file, stanza, key and value is allowed."""
    try:
        require_sourcetype(sourcetype)  # never [default], [source::], [host::] (appsec H1)
    except ValueError as e:
        raise GuardrailBlock(str(e)) from None
    for conf in confs:
        if conf not in CONF_FILES:
            raise GuardrailBlock(f"{conf}.conf is not allowed in a Parsewright add-on")
    prefix = f"parsewright_{job}_"
    own_transforms = set(confs.get("transforms", {}))

    for stanza, settings in confs.get("props", {}).items():
        # Only the job's own test sourcetype: no [default], [source::...], [host::...], [rule::].
        if stanza != sourcetype:
            raise GuardrailBlock(f"props stanza [{stanza}] is not this job's sourcetype")
        for key, value in settings.items():
            k = _key(key, f"props [{stanza}]")
            if FORBIDDEN.match(k):
                raise GuardrailBlock(f"props key {key} is forbidden")
            if k not in PROPS_EXACT and not k.startswith(PROPS_PREFIXES):
                raise GuardrailBlock(f"props key {key} is not on the allowlist")
            if k in INDEX_TIME:  # re-check the value's type and bounds, not just the key
                try:
                    INDEX_TIME[k](value)
                except GuardrailBlock as e:
                    raise GuardrailBlock(f"props {key} {e}") from None
            if k == "KV_MODE" and value not in search_time.KV_MODES:
                raise GuardrailBlock(f"KV_MODE {value!r} is not allowed")
            if k.startswith("REPORT-"):
                for name in (n.strip() for n in value.split(",")):
                    if name not in own_transforms or not name.startswith(prefix):
                        raise GuardrailBlock(
                            f"{key} references transform {name!r} outside this job"
                        )
            if k.startswith("EVAL-"):
                targets = [k.split("-", 1)[1]]
                refs = {r.lower() for r in search_time._references(value)}
                if refs & search_time.ENVIRONMENT or any(r.startswith("_") for r in refs):
                    raise GuardrailBlock(f"{key} depends on where or when it runs")
            elif k.startswith("FIELDALIAS-"):
                targets = ALIAS_TARGETS.findall(norm(value))
                if not targets:
                    raise GuardrailBlock(f"{key} has no AS target")
            else:
                targets = []
            for target in (t.lower() for t in targets):
                if target in CORE_TARGETS or target.startswith("_"):
                    raise GuardrailBlock(f"{key} may not write the core field {target}")

    for stanza, settings in confs.get("transforms", {}).items():
        if not stanza.startswith(prefix):
            raise GuardrailBlock(f"transform [{stanza}] must start with {prefix}")
        for key, value in settings.items():
            k = _key(key, f"transforms [{stanza}]")
            if k not in TRANSFORM_KEYS:
                raise GuardrailBlock(f"transforms key {key} is not on the allowlist")
            if k == "FORMAT" and FORMAT_BLOCK.search(value):
                raise GuardrailBlock(
                    f"transform [{stanza}] FORMAT may not write metadata or queues"
                )

    for stanza, settings in confs.get("eventtypes", {}).items():
        if not stanza.startswith(prefix):
            raise GuardrailBlock(f"eventtype [{stanza}] must start with {prefix}")
        if set(settings) - {"search"}:
            raise GuardrailBlock(f"eventtype [{stanza}] may only set search")
        search = settings.get("search", "")
        anchor = f"sourcetype={sourcetype}"
        if search != anchor:
            inner = search.removeprefix(f"{anchor} (").removesuffix(")")
            if (
                not search.startswith(f"{anchor} (")
                or not search.endswith(")")
                or not search_time._balanced(inner)
                or search_time.FILTER_BLOCK.search(inner)
            ):
                raise GuardrailBlock(f"eventtype [{stanza}] is not anchored on {anchor}")

    allowed_tags = {t for tags in cim_spec.TAGS.values() for t in tags}
    for stanza, settings in confs.get("tags", {}).items():
        name = stanza.removeprefix("eventtype=")
        if stanza == name or name not in confs.get("eventtypes", {}):
            raise GuardrailBlock(f"tags [{stanza}] must tag one of this job's eventtypes")
        for tag, value in settings.items():
            if tag not in allowed_tags or value != "enabled":
                raise GuardrailBlock(f"tag {tag}={value} is not allowed")
