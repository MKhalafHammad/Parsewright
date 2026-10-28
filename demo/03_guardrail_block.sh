#!/usr/bin/env bash
# RECORD THIS: guardrails stopping an attack (Phase 4).
#
# Shows: a log line carrying a prompt injection; a (simulated) compromised model's CIM proposal
# blocked by the gate with its reason and never deployed; a subtler constant that passes the
# gate caught by the Validator; then the real model mapping action correctly.
# Prerequisites: lab running, CIM add-on, .env filled in, make setup done. A few minutes and
# ~100k tokens. See demo/03_guardrail_block.py for the exact attacker proposals.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python demo/03_guardrail_block.py
