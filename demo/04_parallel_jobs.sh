#!/usr/bin/env bash
# RECORD THIS: parallel jobs (Phase 5).
#
# Shows: four log files uploaded at once through the API; four workers take them in parallel;
# three run straight through while the fourth (no auto-approve) pauses for profile review and
# frees its worker; the script then confirms that profile and the job resumes.
# Prerequisites: PostgreSQL (docker compose up -d postgres), lab Splunk, .env filled in, and the
# API with workers running in another terminal:  .venv/bin/parsewright serve --workers 4
# Takes several minutes and roughly 250-400k tokens in total.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python demo/04_parallel_jobs.py
