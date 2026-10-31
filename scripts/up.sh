#!/usr/bin/env bash
# One-command stack for judges and local use (`make up`):
#   1. .env: created from .env.example if missing, placeholder passwords generated;
#   2. Splunk and PostgreSQL started and healthy;
#   3. Splunk prepared (scripts/splunk_bootstrap.py, inside the container): test index, roles,
#      users, the CIM add-on and its index macros, and fresh service tokens written to .env;
#   4. migrations, the engine and the web UI started, and the engine healthy.
# No secret is printed. Set DOCKER="sudo docker" if your user cannot reach the Docker socket.
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKER=${DOCKER:-docker}
compose() { $DOCKER compose "$@"; }

health() { # service -> healthy|starting|unhealthy|exited|missing
  local id
  id=$(compose ps -q "$1" 2>/dev/null || true)
  [ -n "$id" ] || { echo missing; return; }
  $DOCKER inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id"
}

wait_healthy() { # service, seconds
  local s i
  for ((i = 0; i < $2; i += 5)); do
    s=$(health "$1")
    [ "$s" = healthy ] && return 0
    [ "$s" = running ] && return 0 # no healthcheck defined: readiness is checked later
    [ "$s" = unhealthy ] && break
    sleep 5
  done
  echo "$1 is not healthy ($(health "$1")): see '$DOCKER compose logs $1'" >&2
  return 1
}

python3 scripts/init_env.py

echo "starting Splunk and PostgreSQL (Splunk's first start takes a few minutes)"
compose up -d splunk postgres
wait_healthy postgres 120
wait_healthy splunk 900

echo "preparing Splunk"
TEST_INDEX=$(grep -E '^PARSEWRIGHT_TEST_INDEX=' .env | cut -d= -f2- || true)
# The script reaches splunkd on the container's loopback; its stdout is the tokens, which go
# straight into .env and never to the terminal.
tokens=$(compose exec -T -e PW_TEST_INDEX="${TEST_INDEX:-pw_test}" splunk \
  sh -c 'if command -v python3 >/dev/null; then exec python3 -; else exec /opt/splunk/bin/splunk cmd python3 -; fi' \
  < scripts/splunk_bootstrap.py)
printf '%s\n' "$tokens" | python3 scripts/env_set.py
unset tokens

echo "starting the engine and the web UI"
compose up -d --build
wait_healthy engine 300

WEB_PORT=$(grep -E '^WEB_PORT=' .env | cut -d= -f2- || true)
SPLUNK_WEB_PORT=$(grep -E '^SPLUNK_WEB_PORT=' .env | cut -d= -f2- || true)
cat <<EOF

Parsewright is up.
  UI:          http://localhost:${WEB_PORT:-3000}
  Splunk Web:  http://localhost:${SPLUNK_WEB_PORT:-8000}  (user admin, password SPLUNK_PASSWORD in .env)
First run:     make first-run
EOF
