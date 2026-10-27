# guardrails

The deterministic gate every agent output passes: conf key/value allowlist, btool check, regex catastrophic-backtracking test, scope checks.

Status: built: `index_time.py` (allowlist with typed, bounded values). Search-time keys, regex safety and scope planned (Phases 3–4). See [docs/design.md](../../../docs/design.md), section "Guardrails and security".
