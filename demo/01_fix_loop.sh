#!/usr/bin/env bash
# RECORD THIS: the first agent fix loop (Phase 2).
#
# Shows: the Index-time agent's first proposal sets TZ = UTC for logs written in Tokyo time with
# no offset. The Validator catches "60/60 events wrong, offset +32400 s" (9 hours) and returns
# that evidence; the next attempt sets TZ = Asia/Tokyo and passes 60/60 with exact _time.
# Prerequisites: lab running, .env filled in (Splunk tokens, LLM key, PARSEWRIGHT_TEST_INDEX,
# PARSEWRIGHT_PACKAGES_DIR), make setup done. Takes about 1 minute and ~20k tokens.
# The model may get TZ right on the first try; then simply run it again.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/parsewright run engine/parsewright/generator/fixtures/acme_vpn_notz.json \
  --vendor acme --product vpn
