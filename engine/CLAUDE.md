# engine/ conventions (Python)

Root rules in [../CLAUDE.md](../CLAUDE.md) apply. Design: [../docs/design.md](../docs/design.md).

## Language and tooling
- Python 3.12. Type hints on every public function.
- Ruff for lint and format (config in `pyproject.toml`, line length 100). Run `make lint`.
- pytest for tests in `engine/tests/`, mirroring the package layout (`tests/guardrails/test_*.py`).
- Plain Python, no agent framework (design decision).

## Structure
- One package: `parsewright`. Modules match the design's repo structure: `api`, `orchestrator`, `agents`, `tools`, `guardrails`, `validator`, `ta_builder`, `ledger`, `cim_spec`, `generator`.
- Pydantic models for every agent output, tool-call argument, API body and config object. Validate at the boundary; inside, trust the types.
- Configuration comes from environment variables only (see `.env.example`). Never hardcode URLs, model names, tokens or passwords.

## Safety conventions
- SQL: parameterized queries only; state transitions as `UPDATE ... WHERE status = '<expected>'` and check the row count.
- Subprocess: argument lists, never `shell=True`.
- Paths: resolve and verify they stay inside the allowed root; never follow symlinks at intake.
- `.conf` files: only through the one escaping writer in `ta_builder`.
- Splunk: only through `tools` (search guard, scoped tokens); ingest targets must start with `pw_`.
- Timeouts on every Splunk and model call.
- Logging: never log secrets, tokens or full prompts containing credentials; redact before writing to the ledger.
- Untrusted text (logs, form fields, search results) is passed to models as delimited data, never concatenated into instructions.

## Tests
- Every new branch of logic has a test. Every guardrail has an adversarial test that tries to bypass it.
- Tests use only synthetic data from `parsewright/generator/fixtures/`.
