#!/usr/bin/env bash
# Run a Phase 1 lab probe with only the .env keys it needs.
# Usage: scripts/probe.sh llm|splunk|install|update
#
# .env is read as plain KEY=value lines, never sourced: nothing in it runs as shell code,
# values are not expanded, and each probe sees only its own keys.
set -euo pipefail
cd "$(dirname "$0")/.."

splunk_keys="SPLUNK_HOST SPLUNK_PORT SPLUNK_SEARCH_TOKEN SPLUNK_DEPLOY_TOKEN"
case "${1:-}" in
  llm) keys="LLM_API_KEY LLM_BASE_URL LLM_MODEL" ;;
  splunk) keys="$splunk_keys" ;;
  install | update) keys="$splunk_keys PARSEWRIGHT_PACKAGES_DIR PARSEWRIGHT_TEST_INDEX" ;;
  *) echo "usage: scripts/probe.sh llm|splunk|install|update" >&2; exit 2 ;;
esac

[ -f .env ] || { echo ".env not found: run make setup and fill it in" >&2; exit 1; }
while IFS= read -r line || [ -n "$line" ]; do
  line=${line%$'\r'}
  case "$line" in '' | '#'*) continue ;; esac
  key=${line%%=*}
  case " $keys " in *" $key "*) export "$key=${line#*=}" ;; esac
done < .env

exec .venv/bin/python -m "parsewright.tools.probes.probe_$1"
