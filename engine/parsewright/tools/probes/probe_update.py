"""Probe in-place updates (Phase 7): does a reinstall with update=true keep an admin's local/
overrides, and do changed index-time settings on an existing sourcetype apply without a restart?

Installs a throwaway test add-on, writes one admin-style override into its local/ (the only
local/ write anywhere in Parsewright, and only in this probe), reinstalls a v2 with a new
TIME_FORMAT, ingests into the shared PARSEWRIGHT_TEST_INDEX, then uninstalls the add-on.
Never prints tokens.
Run: scripts/probe.sh update
"""

import os
import sys
import time
import uuid
from datetime import UTC, datetime

from splunklib.binding import HTTPError
from splunklib.results import JSONResultsReader

from parsewright.tools.probes.probe_install import (
    APP,
    build_package,
    install,
    packages_dir,
    shared_index,
)
from parsewright.tools.probes.probe_splunk import connect, count, whoami

SOURCETYPE = "pw_probe_upd__test_probe"
STAMPS = ["2026-01-02 03:04:05", "2026-01-02 03:04:06", "2026-01-02 03:04:07"]
BASE = f"""[{SOURCETYPE}]
SHOULD_LINEMERGE = false
LINE_BREAKER = ([\\r\\n]+)
TIME_PREFIX = ts=
TZ = UTC
EXTRACT-a = a=(?<a>\\w+)
"""
PROPS_V1 = BASE + "TIME_FORMAT = %Y-%m-%d %H:%M:%S\nMAX_TIMESTAMP_LOOKAHEAD = 19\n"
# v2: a new timestamp format (day first) for the same sourcetype, and one new extraction.
PROPS_V2 = BASE + "TIME_FORMAT = %d/%m/%Y %H:%M:%S\nMAX_TIMESTAMP_LOOKAHEAD = 19\n"
PROPS_V2 += "EXTRACT-b = b=(?<b>\\w+)\n"
LOCAL_KEY, LOCAL_VALUE = "EXTRACT-local", "l=(?<l>\\w+)"


def expected_epochs() -> list[int]:
    return [int(datetime.fromisoformat(s).replace(tzinfo=UTC).timestamp()) for s in STAMPS]


def effective(service, stanza: str) -> dict[str, str]:
    """The merged settings Splunk applies for a stanza in the app's context (default + local)."""
    import json

    body = service.get(
        f"configs/conf-props/{stanza}", owner="nobody", app=APP, output_mode="json"
    ).body.read()
    content = json.loads(body)["entry"][0]["content"]
    return {k: str(v) for k, v in content.items() if not k.startswith("eai:")}


def app_version(service) -> str:
    import json

    body = service.get(f"apps/local/{APP}", output_mode="json").body.read()
    return str(json.loads(body)["entry"][0]["content"].get("version", ""))


def ingest_times(search, deploy, index: str, lines: list[str]) -> list[int]:
    source = f"parsewright_probe_{uuid.uuid4().hex[:8]}"
    deploy.indexes[index].submit("\n".join(lines), sourcetype=SOURCETYPE, source=source)
    where = f"index={index} sourcetype={SOURCETYPE} source={source}"
    seen = -1
    for _ in range(30):
        time.sleep(2)
        now = count(search, f"| tstats count where {where}")
        if now and now == seen:
            break
        seen = now
    rows = search.jobs.oneshot(
        f"search {where} | eval t=floor(_time) | sort t | table t",
        output_mode="json",
        earliest_time="0",
        count=10,
    )
    return [int(r["t"]) for r in JSONResultsReader(rows) if isinstance(r, dict)]


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
    dest, index = packages_dir(), shared_index()
    v1 = build_package(dest, "1.0.0", PROPS_V1)
    v2 = build_package(dest, "1.1.0", PROPS_V2)
    installed, ok = False, True
    try:
        print(f"install v1: {install(deploy, v1)}")
        installed = True
        times = ingest_times(search, deploy, index, [f"a=x ts={s}" for s in STAMPS])
        print(f"v1 timestamps correct: {times == expected_epochs()}")

        # An admin's override, written the way an admin's UI or REST edit is: into local/.
        deploy.post(
            f"configs/conf-props/{SOURCETYPE}",
            owner="nobody",
            app=APP,
            **{LOCAL_KEY: LOCAL_VALUE, "TZ": "Pacific/Chatham"},
        )
        eff = effective(deploy, SOURCETYPE)
        print(f"after admin edit: {LOCAL_KEY} present={LOCAL_KEY in eff}, TZ={eff.get('TZ')}")

        print(f"reinstall v2 with update=true: {install(deploy, v2)}")
        print(f"installed version: {app_version(deploy)} (expect 1.1.0)")
        eff = effective(deploy, SOURCETYPE)
        kept = eff.get(LOCAL_KEY) == LOCAL_VALUE and eff.get("TZ") == "Pacific/Chatham"
        print(
            f"local/ kept after update: {kept} ({LOCAL_KEY} present={LOCAL_KEY in eff}, "
            f"TZ={eff.get('TZ')}: local still overrides default's UTC)"
        )
        print(
            f"v2 default applied: TIME_FORMAT={eff.get('TIME_FORMAT')!r}, "
            f"EXTRACT-b present={'EXTRACT-b' in eff}"
        )
        ok &= kept and "EXTRACT-b" in eff

        # Remove the admin's TZ override so the timestamp check isolates the TIME_FORMAT change.
        deploy.post(f"configs/conf-props/{SOURCETYPE}", owner="nobody", app=APP, TZ="UTC")
        v2_lines = [f"a=x ts={datetime.fromisoformat(s):%d/%m/%Y %H:%M:%S}" for s in STAMPS]
        times = ingest_times(search, deploy, index, v2_lines)
        applied = times == expected_epochs()
        print(f"changed TIME_FORMAT on the existing sourcetype applied, no reload: {applied}")
        if not applied:
            deploy.get("configs/conf-props/_reload", owner="nobody", app=APP)
            times = ingest_times(search, deploy, index, v2_lines)
            applied = times == expected_epochs()
            print(f"after reload conf-props: {applied}")
        ok &= applied
    finally:
        if installed:
            try:
                deploy.delete(f"apps/local/{APP}")
                print("cleanup: test add-on uninstalled (its local/ with it)")
            except HTTPError as e:
                print(f"cleanup: uninstall refused HTTP {e.status}; remove {APP} by hand")
        for package in (v1, v2):
            package.unlink(missing_ok=True)
    print(f"update probe: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
