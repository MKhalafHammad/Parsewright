# guardrails

The deterministic gate every agent output passes: conf key/value allowlist with typed values, regex catastrophic-backtracking test, scope checks, and a final gate over the whole package.

Status: built: `index_time.py` and `search_time.py` (EXTRACT regexes, DELIMS, FIELDALIAS, EVAL, eventtypes anchored by code, tags from the CIM spec). `conf_gate.py` is the final gate over the whole package (allowlisted keys after Unicode normalisation, no foreign stanzas, eventtype anchoring, CIM provenance). The adversarial suite is in `engine/tests/`. See [docs/design.md](../../../docs/design.md), section "Guardrails and security".
