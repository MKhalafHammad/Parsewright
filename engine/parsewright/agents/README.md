# agents

Muse Spark agents, one module each: profiler, index_time, extraction, cim_mapper (plus router and drift_analyst). Each has a prompt and a Pydantic output schema; none can deploy or write files.

Status: built: `llm.py` (strict JSON schema, token ceiling, bad-output retries), `profiler.py`, `index_time.py`. Extraction and CIM mapper planned (Phase 3). See [docs/design.md](../../../docs/design.md), section "AI agent architecture".
