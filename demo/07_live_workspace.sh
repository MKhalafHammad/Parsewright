#!/usr/bin/env bash
# RECORD THIS: the agent-centred run workspace (UI redesign, before Phase 8).
#
# Shows: the runs board with "Needs you" pinned, the profile review with coverage bars and
# "you changed this" markers, then the live workspace: the Now banner naming the agent at work,
# the phase rail (click a phase, arrow keys move along it), attempts with what each one proposed,
# the gate's verdict, Splunk's checks (expected vs actual) and the diff from the previous attempt
# as readable rows, and the activity feed grouped by phase and attempt.
# Prerequisites: PostgreSQL, lab Splunk and .env as for demo 04, plus in two other terminals:
#   .venv/bin/parsewright serve --workers 2
#   (cd web && ENGINE_URL=http://127.0.0.1:8080 npm run build && npm start)
# Takes 1-3 minutes after you confirm the profile, and ~30k tokens.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python demo/07_live_workspace.py
