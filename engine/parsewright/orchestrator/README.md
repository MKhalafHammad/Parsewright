# orchestrator

Deterministic state machine (one per job), worker pool with FOR UPDATE SKIP LOCKED claims and leases, budgets, retries, backtracking and routing of failures to the owning agent.

Status: built: `run.py` (Profile, auto-approved review, three stages with regression re-runs and one backtrack; state in memory). PostgreSQL state machine and workers planned (Phase 5). See [docs/design.md](../../../docs/design.md), section "Orchestrator state machine".
