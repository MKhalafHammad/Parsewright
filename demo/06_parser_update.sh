#!/usr/bin/env bash
# RECORD THIS: a parser update (Phase 7).
#
#   demo/06_parser_update.sh [patch] [TA name]   firmware v2 samples: Diagnose with no model call,
#                                                only the failing stages patched, old and new
#                                                samples both pass, diff against production
#   demo/06_parser_update.sh diagnose [TA name]  after approving and promoting the update: a new
#                                                v2 batch ends at Diagnose with 0 tokens
# The TA defaults to TA-parsewright-acme-fwdemo (a firewall TA built from acme_fw.log).
# Prerequisites: PostgreSQL, lab Splunk and .env as for demo 04, plus in two other terminals:
#   .venv/bin/parsewright serve --workers 2
#   (cd web && ENGINE_URL=http://127.0.0.1:8080 npm run build && npm start)
# Takes a few minutes and ~30k tokens (patch); about a minute and 0 tokens (diagnose).
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python demo/06_parser_update.py "$@"
