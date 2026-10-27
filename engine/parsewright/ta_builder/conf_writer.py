"""The one escaping .conf writer. Every .conf file Parsewright produces goes through write_conf.

Splunk .conf has no quoting, so safety comes from rejecting anything that could change the
file's structure: newlines (a new line can start a new stanza such as [script://...]), a
trailing backslash (line continuation), control characters, and brackets in stanza names.
"""

import re

KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_.:-]*")
STANZA = re.compile(r"[A-Za-z0-9_.:*-]+(::[^\[\]\r\n]+)?")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class ConfValueError(ValueError):
    pass


def _check_text(text: str, what: str) -> None:
    if "\n" in text or "\r" in text:
        raise ConfValueError(f"{what} contains a newline")
    if CONTROL.search(text):
        raise ConfValueError(f"{what} contains a control character")
    if text.rstrip().endswith("\\"):
        raise ConfValueError(f"{what} ends with a backslash (line continuation)")


def write_conf(stanzas: dict[str, dict[str, str]]) -> str:
    """Render {stanza: {key: value}} as .conf text, or raise ConfValueError."""
    out: list[str] = []
    for stanza, settings in stanzas.items():
        _check_text(stanza, f"stanza {stanza!r}")
        # "" renders [] (app-level scope in metadata/default.meta).
        if stanza and not STANZA.fullmatch(stanza):
            raise ConfValueError(f"stanza name {stanza!r} is not allowed")
        out.append(f"[{stanza}]")
        for key, value in settings.items():
            if not KEY.fullmatch(key):
                raise ConfValueError(f"key {key!r} is not allowed")
            if not isinstance(value, str):
                raise ConfValueError(f"value for {key} must be a string")
            _check_text(value, f"value for {key}")
            out.append(f"{key} = {value}" if value else f"{key} =")
        out.append("")
    return "\n".join(out)
