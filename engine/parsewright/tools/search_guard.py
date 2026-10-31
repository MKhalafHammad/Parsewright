"""run_search guard: what an agent may ask Splunk (threat T1.2).

Code owns the base search: `search index=<test index> sourcetype=<own attempt sourcetype>`.
The agent supplies at most a pipeline of allowlisted commands, each after a `|`. Results are
capped at 50 rows. Subsearches, macros and commands that start a new result set are refused.
"""

import re

from parsewright.ta_builder.naming import require_pw_index
from parsewright.tools.splunk_client import spl_name

MAX_ROWS = 50
MAX_LENGTH = 1000
ALLOWED = frozenset(
    {
        "search",
        "where",
        "eval",
        "stats",
        "eventstats",
        "streamstats",
        "table",
        "fields",
        "rename",
        "head",
        "tail",
        "sort",
        "dedup",
        "top",
        "rare",
        "fieldsummary",
        "rex",
        "regex",
        "spath",
        "bin",
        "chart",
        "timechart",
        "makemv",
        "mvexpand",
        "fillnull",
    }
)  # every other command (delete, collect, dbxquery, loadjob, rest, map, tstats, ...) is refused


class SearchRefused(ValueError):
    pass


def split_pipeline(pipeline: str) -> list[str]:
    """Split on | outside double quotes; refuse brackets and backticks outside quotes."""
    parts, buf, quoted, escaped = [], [], False, False
    for ch in pipeline:
        if quoted and escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            if not quoted:  # fail closed: do not depend on how Splunk reads \| or \[
                raise SearchRefused("escapes are only allowed inside double quotes")
            buf.append(ch)
            escaped = True
        elif ch == "'" and not quoted:
            raise SearchRefused("single quotes are not allowed outside double quotes")
        elif ch == '"':
            buf.append(ch)
            quoted = not quoted
        elif quoted:
            buf.append(ch)
        elif ch in "[]`":
            raise SearchRefused("subsearches and macros are not allowed")
        elif ch == "|":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if quoted:
        raise SearchRefused("unbalanced quotes")
    parts.append("".join(buf))
    return parts


def build_search(index: str, sourcetype: str, pipeline: str = "") -> str:
    """The full SPL for an agent request: fixed base search, checked pipeline, 50-row cap."""
    pipeline = pipeline.strip()
    if len(pipeline) > MAX_LENGTH:
        raise SearchRefused("pipeline too long")
    if "`" in pipeline or re.search(r"\blookup\s*\(", pipeline, re.IGNORECASE):
        raise SearchRefused("macros and the lookup() function are not allowed")
    if pipeline and not pipeline.startswith("|"):
        raise SearchRefused("the pipeline must start with |; the base search is fixed")
    commands = split_pipeline(pipeline)[1:] if pipeline else []
    for part in commands:
        match = re.match(r"\s*([A-Za-z_]+)", part)
        name = match.group(1).lower() if match else ""
        if name not in ALLOWED:
            raise SearchRefused(f"command {name or '(empty)'!r} is not allowed")
    base = f"search index={require_pw_index(index)} sourcetype={spl_name(sourcetype)}"
    return f"{base} {pipeline} | head {MAX_ROWS}".replace("  ", " ")
