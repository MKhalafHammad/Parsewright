#!/usr/bin/env bash
# Run a Phase 1 lab probe with .env loaded into this process only.
# Usage: scripts/probe.sh llm|splunk|install
set -euo pipefail
cd "$(dirname "$0")/.."

case "${1:-}" in
  llm | splunk | install) ;;
  *) echo "usage: scripts/probe.sh llm|splunk|install" >&2; exit 2 ;;
esac

[ -f .env ] || { echo ".env not found: run make setup and fill it in" >&2; exit 1; }
set -a
. ./.env
set +a
exec .venv/bin/python -m "parsewright.tools.probes.probe_$1"
