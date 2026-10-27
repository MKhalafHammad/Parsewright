"""Probe the Splunk lab: token scopes, search limits and the receivers/simple ingest path.

Writes only to the pw_probe index (create it first). Never prints tokens.
Run: python -m parsewright.tools.probes.probe_splunk
     (reads SPLUNK_HOST, SPLUNK_PORT, SPLUNK_SEARCH_TOKEN, SPLUNK_DEPLOY_TOKEN)
"""

import base64
import binascii
import json
import os
import re
import sys
import time

import splunklib.client as client
import splunklib.results as results
from splunklib.binding import AuthenticationError, HTTPError

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


def token_shape(token: str) -> str:
    """Describe a Splunk token without revealing it: length, form, and the JWT's user and expiry.

    The signature (the secret part) is never decoded or printed.
    """
    notes = [f"length={len(token)}"]
    if token != token.strip():
        notes.append("has leading/trailing whitespace")
    if token[:1] in "\"'" or token[-1:] in "\"'":
        notes.append("has quote characters")
    parts = token.strip().strip("\"'").split(".")
    if len(parts) != 3:
        return ", ".join([*notes, f"not a JWT ({len(parts)} parts, expected 3): copied wrong?"])
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error):
        return ", ".join([*notes, "payload not decodable: copied wrong?"])
    notes.append(f"user={claims.get('sub')}")
    if "exp" in claims:
        left = int(claims["exp"]) - int(time.time())
        notes.append("EXPIRED" if left <= 0 else f"expires in {left // 3600}h")
    return ", ".join(notes)


def whoami(service: client.Service, label: str, token: str) -> bool:
    try:
        body = service.get("authentication/current-context", output_mode="json").body.read()
    except AuthenticationError:
        print(f"{label}: REJECTED by Splunk (401). Token shape: {token_shape(token)}")
        return False
    content = json.loads(body)["entry"][0]["content"]
    caps = sorted(INTERESTING & set(content.get("capabilities", [])))
    print(f"{label}: user={content['username']} roles={content['roles']} notable_caps={caps}")
    return True


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
    search_token = os.environ["SPLUNK_SEARCH_TOKEN"]
    deploy_token = os.environ["SPLUNK_DEPLOY_TOKEN"]
    search = connect(search_token)
    deploy = connect(deploy_token)
    ok = whoami(search, "search token", search_token)
    ok = whoami(deploy, "deploy token", deploy_token) and ok
    if not ok:
        print("stopping: fix the rejected token in .env and run again")
        return 1

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
    try:
        deploy.indexes[index].submit(lines, sourcetype="pw_probe", source="parsewright_probe")
    except HTTPError as e:
        hint = " (deploy role likely lacks edit_tcp)" if e.status == 403 else ""
        print(f"receivers/simple: refused HTTP {e.status}{hint}")
        return 1
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
