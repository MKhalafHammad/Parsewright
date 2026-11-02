#!/usr/bin/env bash
# RECORD THIS: just the log, no answer key.
#
#   demo/08_log_only.sh [fw]      a fresh firewall log alone: built and proven on every event
#                                 with no manifest; the report lists the agents' decisions
#   demo/08_log_only.sh timezone  a fresh VPN log in local time: the run asks for the timezone
#                                 in profile review, then continues
# Prerequisites: PostgreSQL, lab Splunk and .env as for demo 04, plus the engine and web UI
# running (see the README's Usage). Takes a few minutes and ~80k tokens.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python demo/08_log_only.py "$@"
