# guardrails

The deterministic gate every agent output passes: conf key/value allowlist, btool check, regex catastrophic-backtracking test, scope checks.

Status: built: `index_time.py` and `search_time.py` (EXTRACT regexes, DELIMS, FIELDALIAS, EVAL, eventtypes anchored by code, tags from the CIM spec). Full adversarial suite planned (Phase 4). See [docs/design.md](../../../docs/design.md), section "Guardrails and security".
