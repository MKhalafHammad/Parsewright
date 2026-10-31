#!/usr/bin/env bash
# RECORD THIS: the first green CIM check (Phase 3).
#
# Shows: one log file goes through all three stages (index-time, extraction, CIM mapping),
# each checked by Splunk, and ends with the holdout line ("learned from 200 lines, passed on
# the full file (300 events)") and the three CIM numbers per data model.
# Prerequisites: lab running, CIM add-on with pw_* in its index macros, .env filled in,
# make setup done. Takes a few minutes and roughly 50-100k tokens per fixture.
# Usage: demo/02_cim_green.sh [vpn|fw|ssh|proxy]   (default: vpn)
set -euo pipefail
cd "$(dirname "$0")/.."
fixtures=engine/parsewright/generator/fixtures
case "${1:-vpn}" in
  vpn) args=("$fixtures/acme_vpn.json" --vendor acme --product vpn) ;;
  fw) args=("$fixtures/acme_fw.log" --vendor acme --product firewall) ;;
  ssh) args=("$fixtures/acme_ssh.log" --vendor acme --product bastion --tz UTC) ;;
  proxy) args=("$fixtures/acme_proxy.csv" --vendor acme --product proxy) ;;
  *) echo "usage: demo/02_cim_green.sh [vpn|fw|ssh|proxy]" >&2; exit 2 ;;
esac
exec .venv/bin/parsewright run --local "${args[@]}"
