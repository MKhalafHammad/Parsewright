"""Probe the add-on install path (Q6), index-time settings after install (Q3) and the deploy
role's install capabilities (Q9).

Installs a throwaway test add-on, ingests into the shared PARSEWRIGHT_TEST_INDEX only,
then uninstalls it.
Never prints tokens.
Run: python -m parsewright.tools.probes.probe_install
     (reads SPLUNK_HOST, SPLUNK_PORT, SPLUNK_SEARCH_TOKEN, SPLUNK_DEPLOY_TOKEN,
      PARSEWRIGHT_TEST_INDEX: the shared pw_ test index, created once by an admin,
      PARSEWRIGHT_PACKAGES_DIR: a directory on the Splunk host that splunkd can read)
"""

import io
import os
import stat
import sys
import tarfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from splunklib.binding import HTTPError
from splunklib.results import JSONResultsReader

from parsewright.tools.probes.probe_splunk import (
    connect,
    count,
    require_pw_index,
    whoami,
)

APP = "TA-parsewright-acme-probe__test_probe"
SOURCETYPE_V1 = "pw_probe_lb__test_probe"
SOURCETYPE_V2 = "pw_probe_v2__test_probe"
# An unusual zone with a 45-minute offset, so a match cannot come from the server's own zone.
TZ = "Pacific/Chatham"
STAMPS = ["2026-01-02 03:04:05", "2026-01-02 03:04:06", "2026-01-02 03:04:07"]

# shortcut: fixed literals, no untrusted values, so the Phase 2 escaping writer isn't needed yet.
PROPS_V1 = f"""[{SOURCETYPE_V1}]
SHOULD_LINEMERGE = false
LINE_BREAKER = (;)
TIME_PREFIX = ts=
TIME_FORMAT = %Y-%m-%d %H:%M:%S
MAX_TIMESTAMP_LOOKAHEAD = 19
TZ = {TZ}
"""
PROPS_V2 = f"""[{SOURCETYPE_V2}]
SHOULD_LINEMERGE = false
LINE_BREAKER = (;)
"""
APP_CONF = """[install]
state = enabled

[ui]
is_visible = false
label = Parsewright install probe

[launcher]
version = {version}
description = Throwaway add-on for the Parsewright Phase 1 install probe.
"""
DEFAULT_META = """[]
access = read : [ * ], write : [ admin ]
export = system
"""


def expected_epochs() -> list[int]:
    zone = ZoneInfo(TZ)
    return [int(datetime.fromisoformat(s).replace(tzinfo=zone).timestamp()) for s in STAMPS]


def packages_dir() -> Path:
    """The packages folder: absolute, a real directory (not a symlink), owned by this user and
    not group- or world-writable, so nobody else can swap a package before splunkd reads it."""
    raw = os.environ.get("PARSEWRIGHT_PACKAGES_DIR", "")
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise ValueError("PARSEWRIGHT_PACKAGES_DIR must be an absolute path")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise ValueError(f"PARSEWRIGHT_PACKAGES_DIR does not exist: {path}") from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"PARSEWRIGHT_PACKAGES_DIR must be a real directory, not a link: {path}")
    if st.st_uid != os.geteuid():
        raise ValueError(f"PARSEWRIGHT_PACKAGES_DIR must be owned by the engine user: {path}")
    if st.st_mode & 0o022:
        raise ValueError(f"PARSEWRIGHT_PACKAGES_DIR must not be group- or world-writable: {path}")
    return path


def shared_index() -> str:
    """The one shared pw_ index all test ingests go to; attempts differ by sourcetype."""
    return require_pw_index(os.environ.get("PARSEWRIGHT_TEST_INDEX", ""))


def build_package(dest: Path, version: str, props: str) -> Path:
    """Write a complete test add-on .tgz into dest under a fresh name and return its path.

    O_EXCL and O_NOFOLLOW refuse to write through a planted file or symlink.
    """
    files = {
        "default/app.conf": APP_CONF.format(version=version),
        "default/props.conf": props,
        "metadata/default.meta": DEFAULT_META,
    }
    out = dest / f"{APP}-{version}-{uuid.uuid4().hex[:8]}.tgz"
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    os.fchmod(fd, 0o644)  # splunkd runs as another user and must read it; ignore the umask
    with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tar:
        for rel, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{APP}/{rel}")
            info.size, info.mode, info.mtime = len(data), 0o644, int(time.time())
            tar.addfile(info, io.BytesIO(data))
    return out


def install(service, package: Path) -> str:
    """Install or update from a path on the Splunk host. Returns 'ok' or the refusal."""
    try:
        service.post("apps/local", name=str(package), filename=True, update=True)
    except HTTPError as e:
        return f"refused HTTP {e.status}"
    return "ok"


def stanza_present(service, sourcetype: str) -> bool:
    try:
        service.get(f"configs/conf-props/{sourcetype}", owner="nobody", app=APP)
    except HTTPError as e:
        if e.status == 404:
            return False
        raise
    return True


def reload_props(service) -> str:
    try:
        service.get("configs/conf-props/_reload", owner="nobody", app=APP)
    except HTTPError as e:
        return f"refused HTTP {e.status}"
    return "ok"


def ingest_and_check(search, deploy, index: str, label: str) -> bool:
    """Send a;b;c under the v1 sourcetype and check line breaking and timestamps."""
    index = require_pw_index(index)
    source = f"parsewright_probe_{uuid.uuid4().hex[:8]}"
    body = ";".join(f"probe {c} ts={s}" for c, s in zip("abc", STAMPS, strict=True))
    deploy.indexes[index].submit(body, sourcetype=SOURCETYPE_V1, source=source)

    where = f"index={index} sourcetype={SOURCETYPE_V1} source={source}"
    seen, stable = 0, 0
    for _ in range(30):  # wait until two consecutive polls match, as the Validator will
        time.sleep(2)
        now = count(search, f"| tstats count where {where}")
        stable = stable + 1 if now == seen and now > 0 else 0
        seen = now
        if stable >= 1:
            break

    rows = search.jobs.oneshot(
        f"search {where} | eval t=floor(_time) | sort t | table t",
        output_mode="json",
        earliest_time="0",
        count=10,
    )
    times = [int(r["t"]) for r in JSONResultsReader(rows) if isinstance(r, dict)]
    breaking = seen == 3
    stamps = times == expected_epochs()
    lb = "applied" if breaking else "NOT applied"
    ts = "matches" if stamps else "does NOT match"
    print(f"{label}: {seen} events (expect 3: LINE_BREAKER {lb}), _time {ts} TIME_FORMAT+TZ")
    return breaking and stamps


def main() -> int:
    search_token = os.environ["SPLUNK_SEARCH_TOKEN"]
    deploy_token = os.environ["SPLUNK_DEPLOY_TOKEN"]
    search, deploy = connect(search_token), connect(deploy_token)
    if not (
        whoami(search, "search token", search_token)
        and whoami(deploy, "deploy token", deploy_token)
    ):
        print("stopping: fix the rejected token in .env and run again")
        return 1

    dest = packages_dir()
    v1 = build_package(dest, "0.0.1", PROPS_V1)
    v2 = build_package(dest, "0.0.2", PROPS_V2)
    # One shared index, created once by an admin; the engine never creates or deletes indexes.
    index = shared_index()
    print(f"test index: {index} (exists: {index in deploy.indexes})")
    installed = False
    ok = True
    try:
        refused = install(search, v1)
        ok &= refused != "ok"
        installed = refused == "ok"
        verdict = "good" if refused != "ok" else "SECURITY FAIL: search token can install apps"
        print(f"install with search token: {refused} ({verdict})")

        result = install(deploy, v1)
        print(f"install v1 with deploy token: {result}")
        if result != "ok":
            print("stopping: the deploy role cannot install apps (Q9)")
            return 1
        installed = True
        print(f"v1 stanza present after install: {stanza_present(deploy, SOURCETYPE_V1)}")

        applied = ingest_and_check(search, deploy, index, "ingest right after install, no reload")
        if not applied:
            print(f"reload conf-props: {reload_props(deploy)}")
            applied = ingest_and_check(search, deploy, index, "ingest after reload")
        ok &= applied

        result = install(deploy, v2)
        print(f"reinstall v2 with update=true: {result}")
        old, new = stanza_present(deploy, SOURCETYPE_V1), stanza_present(deploy, SOURCETYPE_V2)
        replaced = not old and new
        print(
            f"after v2: v1 stanza present={old}, v2 stanza present={new} "
            f"({'full replace' if replaced else 'NOT a full replace'})"
        )
        ok &= result == "ok" and replaced
    finally:
        if installed:
            try:
                deploy.delete(f"apps/local/{APP}")
                print("cleanup: test add-on uninstalled")
            except HTTPError as e:
                print(f"cleanup: uninstall refused HTTP {e.status}; remove {APP} by hand")
        for package in (v1, v2):
            package.unlink(missing_ok=True)

    print(f"install probe: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
