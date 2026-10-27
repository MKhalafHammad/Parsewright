"""Probe the Splunk lab: token scopes, search limits and the receivers/simple ingest path.

Writes only to the pw_probe index (create it first). Never prints tokens.
Run: python -m parsewright.tools.probes.probe_splunk
     (reads SPLUNK_HOST, SPLUNK_PORT, SPLUNK_SEARCH_TOKEN, SPLUNK_DEPLOY_TOKEN)
"""

import json
import os
import re
import sys
import time

import splunklib.client as client
import splunklib.results as results
from splunklib.binding import HTTPError

PROBE_INDEX = "pw_probe"
# Capabilities the deploy role may need; printed so the owner can trim the role (Q9).
INTERESTING = {
    "admin_all_objects",
    "edit_local_apps",
    "install_apps",
    "rest_apps_management",
    "indexes_edit",
    "edit_monitor",
    "edit_tcp",
    "edit_token_http",
}


def require_pw_index(index: str) -> str:
    # Full match, not a prefix check: the name is also interpolated into SPL.
    if not re.fullmatch(r"pw_[a-z0-9_-]+", index):
        raise ValueError(f"refusing to ingest into {index!r}: test indexes must start with pw_")
    return index


def connect(token: str) -> client.Service:
    # shortcut: TLS verify off for the self-signed lab cert (design "Deferred"); enable for prod.
    return client.connect(
        host=os.environ["SPLUNK_HOST"],
        port=int(os.environ.get("SPLUNK_PORT", "8089")),
        splunkToken=token,
        verify=False,
        autologin=False,
    )


def whoami(service: client.Service, label: str) -> None:
    body = service.get("authentication/current-context", output_mode="json").body.read()
    content = json.loads(body)["entry"][0]["content"]
    caps = sorted(INTERESTING & set(content.get("capabilities", [])))
    print(f"{label}: user={content['username']} roles={content['roles']} notable_caps={caps}")


def count(service: client.Service, spl: str) -> int:
    rows = [
        r
        for r in results.JSONResultsReader(
            service.jobs.oneshot(spl, output_mode="json", earliest_time="0")
        )
        if isinstance(r, dict)
    ]
    return int(rows[0].get("count", 0)) if rows else 0


def main() -> int:
    search = connect(os.environ["SPLUNK_SEARCH_TOKEN"])
    deploy = connect(os.environ["SPLUNK_DEPLOY_TOKEN"])
    whoami(search, "search token")
    whoami(deploy, "deploy token")

    index = require_pw_index(PROBE_INDEX)
    tstats = f"| tstats count where index={index}"
    print(f"search {index}: count={count(search, tstats)} (should run without error)")
    other = "| tstats count where index=* NOT index=pw_* NOT index=_internal"
    try:
        hidden = count(search, other)
        print(f"search other indexes: count={hidden} (expect 0: only pw_* and _internal visible)")
    except HTTPError as e:
        print(f"search other indexes: refused HTTP {e.status} (good)")

    before = count(search, tstats)
    lines = "\n".join(f"probe line {i} ts={int(time.time())}" for i in range(3))
    deploy.indexes[index].submit(lines, sourcetype="pw_probe", source="parsewright_probe")
    seen, stable = before, 0
    for _ in range(30):  # wait until two consecutive polls match, as the Validator will
        time.sleep(2)
        now = count(search, tstats)
        stable = stable + 1 if now == seen and now > before else 0
        seen = now
        if stable >= 1:
            break
    added = seen - before
    verdict = "line breaking applied" if added == 3 else "NOT split per line" if added == 1 else "?"
    print(f"receivers/simple: posted 3 lines, indexed {added} events ({verdict})")
    return 0 if added in (1, 3) else 1


if __name__ == "__main__":
    sys.exit(main())
