#!/usr/bin/env bash
# RECORD THIS: the approval report (Phase 6).
#
# Shows: raw vs parsed side by side with highlights, the mapping table and CIM scores, then
# approve and download the .tgz; a log line containing a <script> tag renders as plain text.
# Prerequisites: PostgreSQL, lab Splunk and .env as for demo 04, plus in two other terminals:
#   .venv/bin/parsewright serve --workers 2
#   (cd web && ENGINE_URL=http://127.0.0.1:8080 npm run build && npm start)
# Takes a few minutes and ~100k tokens.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python demo/05_approval_report.py
