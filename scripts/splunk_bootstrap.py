"""Prepare the bundled Splunk for Parsewright. Runs INSIDE the splunk container (scripts/up.sh
pipes it to the container's python3), against https://127.0.0.1:8089, as admin, using the
SPLUNK_PASSWORD the container already has. Port 8089 stays unpublished.

Idempotent. Creates the test index, the three no-inheritance roles and users from
docs/lab-findings.md (Q9), installs the CIM add-on from a package in /opt/parsewright/lab if
it is not installed, points the CIM index macros at pw_*, then replaces each service user's
tokens with one fresh token, valid 7 days (`make up` again renews them). Progress goes to stderr; the only stdout is KEY=VALUE token lines
for scripts/env_set.py, which writes them to .env without printing them.

Standard library only (the container's python3); the lab's self-signed certificate is accepted
for this loopback connection only.
"""

import base64
import glob
import json
import os
import re
import secrets
import ssl
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://127.0.0.1:8089"
INDEX = os.environ.get("PW_TEST_INDEX", "pw_test")
# `make up` mints new tokens each time; a short life limits a leaked deploy token (T7.4).
TOKEN_LIFETIME = "+7d"  # nosec B105 - a duration, not a secret
CIM_APP = "Splunk_SA_CIM"
CIM_MODELS = (
    "Authentication",
    "Network_Traffic",
    "Web",
)  # engine/parsewright/cim_spec ROOT
ROLES = {
    # Search only pw_* and _internal (agents' searches and the Validator).
    "parsewright_search": {
        "capabilities": ["search"],
        "srchIndexesAllowed": ["pw_*", "_internal"],
        "srchIndexesDefault": ["pw_*"],
    },
    # Install apps and ingest: the final deploy role from lab-findings Q9.
    "parsewright_deploy": {
        "capabilities": ["admin_all_objects", "edit_tcp", "install_apps"],
        "srchIndexesAllowed": ["pw_*"],
        "srchIndexesDefault": ["pw_*"],
    },
    # Read-only (Phase 8 adds a search filter).
    "parsewright_drift": {
        "capabilities": ["search"],
        "srchIndexesAllowed": ["pw_*"],
        "srchIndexesDefault": ["pw_*"],
    },
}
TOKEN_ENV = {
    "parsewright_search": "SPLUNK_SEARCH_TOKEN",
    "parsewright_deploy": "SPLUNK_DEPLOY_TOKEN",
    "parsewright_drift": "SPLUNK_DRIFT_TOKEN",
}

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE  # loopback to this container's own splunkd only
AUTH = (
    "Basic "
    + base64.b64encode(("admin:" + os.environ["SPLUNK_PASSWORD"]).encode()).decode()
)


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def call(method, path, data=None):
    """(status, parsed JSON or None). Never raises on HTTP errors; the caller decides."""
    body = (
        urllib.parse.urlencode(data or {}, doseq=True).encode()
        if data is not None
        else None
    )
    sep = "&" if "?" in path else "?"
    req = urllib.request.Request(
        BASE + path + sep + "output_mode=json", data=body, method=method
    )
    req.add_header("Authorization", AUTH)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:  # nosec B310 - fixed https loopback URL
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def must(status, what):
    if status >= 300:
        log(f"FAILED: {what} (HTTP {status})")
        sys.exit(1)


def wait_ready(limit=600):
    start = time.time()
    while time.time() - start < limit:
        try:
            if call("GET", "/services/server/info")[0] == 200:
                return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(5)
    log("FAILED: splunkd did not answer on 8089")
    sys.exit(1)


def password():
    alphabet = string.ascii_letters + string.digits
    return "".join(
        secrets.choice(alphabet) for _ in range(40)
    )  # never kept: tokens authenticate


def main():
    if not re.fullmatch(r"pw_[a-z0-9_-]{1,60}", INDEX):  # only pw_ test indexes, ever
        log("FAILED: PARSEWRIGHT_TEST_INDEX must look like pw_<name>")
        sys.exit(1)
    wait_ready()
    must(
        call("POST", "/services/admin/token-auth/tokens_auth", {"disabled": "false"})[
            0
        ],
        "enable token authentication",
    )
    log("token authentication: enabled")

    if call("GET", "/services/data/indexes/" + INDEX)[0] == 404:
        # A size cap, not an age limit: sample events carry historical timestamps (Q9).
        must(
            call(
                "POST",
                "/services/data/indexes",
                {"name": INDEX, "maxTotalDataSizeMB": "2000"},
            )[0],
            "create index " + INDEX,
        )
        log(f"index {INDEX}: created")
    else:
        log(f"index {INDEX}: exists")

    for role, spec in ROLES.items():
        exists = call("GET", "/services/authorization/roles/" + role)[0] == 200
        data = dict(spec, imported_roles=[""] if exists else [])
        path = "/services/authorization/roles" + ("/" + role if exists else "")
        if not exists:
            data["name"] = role
        must(call("POST", path, data)[0], "role " + role)
        log("role {}: {}".format(role, "updated" if exists else "created"))

    for user in ROLES:
        if call("GET", "/services/authentication/users/" + user)[0] == 404:
            must(
                call(
                    "POST",
                    "/services/authentication/users",
                    {"name": user, "password": password(), "roles": user},
                )[0],
                "user " + user,
            )
            log(f"user {user}: created")
        else:
            must(
                call("POST", "/services/authentication/users/" + user, {"roles": user})[
                    0
                ],
                "user " + user,
            )
            log(f"user {user}: exists, role set")

    if call("GET", "/services/apps/local/" + CIM_APP)[0] == 404:
        found = glob.glob("/opt/parsewright/lab/splunk-common-information-model-*.tgz")
        found += glob.glob("/opt/parsewright/lab/Splunk_SA_CIM*.tgz")
        if len(found) != 1 or os.path.islink(found[0]):
            log(
                "FAILED: the CIM add-on is not installed; put exactly one CIM package "
                "(a regular file, not a link) in lab/ (see lab/README.md)"
            )
            sys.exit(2)
        must(
            call(
                "POST", "/services/apps/local", {"name": found[0], "filename": "true"}
            )[0],
            "install the CIM add-on",
        )
        log(
            f"CIM add-on: installed from lab/{os.path.basename(found[0])}; restarting splunkd"
        )
        call("POST", "/services/server/control/restart")
        time.sleep(20)
        wait_ready()
    status, app = call("GET", "/services/apps/local/" + CIM_APP)
    must(status, "read the CIM add-on")
    version = (
        ((app or {}).get("entry") or [{}])[0].get("content", {}).get("version", "?")
    )
    log(f"CIM add-on: version {version} (Parsewright's checks are pinned to 8.7.0)")
    for model in CIM_MODELS:
        macro = f"cim_{model}_indexes"
        path = f"/servicesNS/nobody/{CIM_APP}/admin/macros/{macro}"
        must(call("POST", path, {"definition": "(index=pw_*)"})[0], "macro " + macro)
    log("CIM index macros: (index=pw_*) for {}".format(", ".join(CIM_MODELS)))

    # One fresh token per service user; earlier ones are deleted, so a rebuilt .env never
    # leaves a valid old token behind.
    lines = []
    for user, key in TOKEN_ENV.items():
        status, listing = call(
            "GET", f"/services/authorization/tokens?username={user}&count=0"
        )
        must(status, "list tokens of " + user)
        for entry in (listing or {}).get("entry", []):
            claims = (entry.get("content") or {}).get("claims") or {}
            if claims.get("sub") != user:  # never touch another account's token
                continue
            path = "/services/authorization/tokens/{}?id={}".format(
                user, urllib.parse.quote(entry["name"])
            )
            must(call("DELETE", path)[0], "delete an old token of " + user)
        status, made = call(
            "POST",
            "/services/authorization/tokens",
            {"name": user, "audience": "parsewright", "expires_on": TOKEN_LIFETIME},
        )
        must(status, "token for " + user)
        lines.append("{}={}".format(key, made["entry"][0]["content"]["token"]))
        log(f"token for {user}: created")
    sys.stdout.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
