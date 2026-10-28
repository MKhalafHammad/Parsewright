"""TA, test-identity and index naming rules (design: "Test identity", "TA builder")."""

import re

PART = re.compile(r"[a-z0-9_:-]+")
JOB = re.compile(r"[a-z0-9]{4,16}")
INDEX = re.compile(r"pw_[a-z0-9_-]+")
TEST_APP = re.compile(r"TA-parsewright-[a-z0-9_:-]+-[a-z0-9_:-]+__test_[a-z0-9]{4,16}")
TA = re.compile(r"TA-parsewright-[a-z0-9_:-]+-[a-z0-9_:-]+")
TA_PREFIX = "TA-parsewright-"


def _part(value: str, what: str) -> str:
    if not PART.fullmatch(value):
        raise ValueError(f"{what} {value!r} must match ^[a-z0-9_:-]+$")
    return value


def require_job(job: str) -> str:
    if not JOB.fullmatch(job):
        raise ValueError(f"job id {job!r} must match ^[a-z0-9]{{4,16}}$")
    return job


def ta_name(vendor: str, product: str) -> str:
    return f"{TA_PREFIX}{_part(vendor, 'vendor')}-{_part(product, 'product')}"


def test_app(vendor: str, product: str, job: str) -> str:
    return f"{ta_name(vendor, product)}__test_{require_job(job)}"


RESERVED_SOURCETYPES = {"default"}


def require_sourcetype(sourcetype: str) -> str:
    """A props stanza name that can only be a sourcetype stanza, and never [default] (H1)."""
    _part(sourcetype, "sourcetype")
    if "::" in sourcetype:  # would make a source::, host:: or rule:: stanza, not a sourcetype
        raise ValueError(f"sourcetype {sourcetype!r} must not contain '::'")
    if sourcetype in RESERVED_SOURCETYPES:
        raise ValueError(f"sourcetype {sourcetype!r} is reserved")
    return sourcetype


def test_sourcetype(sourcetype: str, job: str, attempt: int) -> str:
    """Each attempt gets a new sourcetype: the case proven to apply without reload (Q3)."""
    if attempt < 1:
        raise ValueError("attempt starts at 1")
    return f"{require_sourcetype(sourcetype)}__test_{require_job(job)}_a{attempt}"


def require_test_app(app: str) -> str:
    """Guard for every install or uninstall call made with the near-admin deploy token (T7.4)."""
    if not TEST_APP.fullmatch(app):
        raise ValueError(f"refusing app {app!r}: not a Parsewright test app")
    return app


def require_real_app(app: str) -> str:
    """Guard for promotion: a Parsewright TA name with no test suffix."""
    if not TA.fullmatch(app) or "__test_" in app:
        raise ValueError(f"refusing app {app!r}: not a Parsewright TA name")
    return app


def require_pw_index(index: str) -> str:
    """Full match, not a prefix check: the name is also interpolated into SPL (T5.1)."""
    if not INDEX.fullmatch(index):
        raise ValueError(f"refusing index {index!r}: test indexes must match pw_[a-z0-9_-]+")
    return index
