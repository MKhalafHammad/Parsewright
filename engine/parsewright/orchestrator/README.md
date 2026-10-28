# orchestrator

Deterministic state machine (one per job), worker pool with FOR UPDATE SKIP LOCKED claims and leases, budgets, retries, backtracking and routing of failures to the owning agent.

Status: built: `run.py` (three stages, resumable), `worker.py` (claims, heartbeats, checkpoints, review pause, budgets), `promote.py`, `caps.py`. See [docs/design.md](../../../docs/design.md), section "Orchestrator state machine".
