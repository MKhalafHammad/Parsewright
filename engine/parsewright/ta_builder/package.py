"""Build a complete TA package (.tgz) safely, under the package file allowlist.

Threats: T2.2, T3.4 (file allowlist), T5.9 (packages folder and swap between build and install).
"""

import gzip
import hashlib
import io
import os
import re
import stat
import tarfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from parsewright.ta_builder.conf_writer import write_conf
from parsewright.ta_builder.naming import require_real_app, require_test_app

# Package file allowlist: parsing config and metadata only; no bin/, no appserver/.
ALLOWED_FILES = re.compile(
    r"default/(app|props|transforms|eventtypes|tags)\.conf|metadata/default\.meta|"
    r"lookups/[a-z0-9_]+\.csv|README(\.md)?"
)
MTIME = 1_700_000_000  # fixed member mtime for reproducible packages
DEFAULT_META = {"": {"access": "read : [ * ], write : [ admin ]", "export": "system"}}
DESCRIPTION = "Built and tested by Parsewright."  # app.conf marker; an update checks it


@dataclass(frozen=True)
class Package:
    path: Path
    app: str
    sha256: str


def packages_dir(raw: Path) -> Path:
    """A real directory (not a link), owned by this user, not group- or world-writable."""
    if not raw.is_absolute():
        raise ValueError("PARSEWRIGHT_PACKAGES_DIR must be an absolute path")
    try:
        st = os.lstat(raw)
    except FileNotFoundError:
        raise ValueError(f"PARSEWRIGHT_PACKAGES_DIR does not exist: {raw}") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"PARSEWRIGHT_PACKAGES_DIR must be a real directory, not a link: {raw}")
    if st.st_uid != os.geteuid():
        raise ValueError(f"PARSEWRIGHT_PACKAGES_DIR must be owned by the engine user: {raw}")
    if st.st_mode & 0o022:
        raise ValueError(f"PARSEWRIGHT_PACKAGES_DIR must not be group- or world-writable: {raw}")
    return raw


def app_conf(app: str, version: str) -> dict[str, dict[str, str]]:
    return {
        "install": {"state": "enabled"},
        "ui": {"is_visible": "false", "label": app},
        "launcher": {"version": version, "description": DESCRIPTION},
    }


def build(
    dest: Path, app: str, version: str, confs: dict[str, dict[str, dict[str, str]]]
) -> Package:
    """Write the full add-on: every stage's stanzas, never a delta (update=true replaces all, Q6).

    confs maps a conf file name ("props") to its stanzas. Files are rendered by the escaping
    writer; the archive is created with O_EXCL|O_NOFOLLOW under a fresh name.
    """
    require_test_app(app)
    return _write(dest, app, version, confs)


def build_promoted(dest: Path, app: str, version: str, confs: dict) -> Package:
    """The real-name package for promotion: same writer, allowlist and file safety."""
    require_real_app(app)
    return _write(dest, app, version, confs)


def _write(dest: Path, app: str, version: str, confs: dict) -> Package:
    for name in confs:
        if not ALLOWED_FILES.fullmatch(f"default/{name}.conf"):
            raise ValueError(f"file default/{name}.conf is not on the package allowlist")
    files = {f"default/{name}.conf": write_conf(stanzas) for name, stanzas in confs.items()}
    files["default/app.conf"] = write_conf(app_conf(app, version))
    files["metadata/default.meta"] = write_conf(DEFAULT_META)

    out = packages_dir(dest) / f"{app}-{version}-{uuid.uuid4().hex[:8]}.tgz"
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    os.fchmod(fd, 0o644)  # splunkd runs as another user and must read it
    # Deterministic bytes (fixed mtimes, sorted members): the same files give the same hash,
    # so a promoted package can be rebuilt and checked.
    with (
        os.fdopen(fd, "wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as tar,
    ):
        for rel, text in sorted(files.items()):
            data = text.encode()
            info = tarfile.TarInfo(f"{app}/{rel}")
            info.size, info.mode, info.mtime = len(data), 0o644, MTIME
            tar.addfile(info, io.BytesIO(data))
    return Package(path=out, app=app, sha256=sha256(out))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
