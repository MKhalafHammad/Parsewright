# agents

Muse Spark agents, one module each: profiler, index_time, extraction, cim_mapper (plus router and drift_analyst). Each has a prompt and a Pydantic output schema; none can deploy or write files.

Status: built: `llm.py`, `profiler.py`, `index_time.py`, `extraction.py`, `cim_mapper.py`. Router and Drift Analyst planned (stretch). See [docs/design.md](../../../docs/design.md), section "AI agent architecture".
