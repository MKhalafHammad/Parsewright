# orchestrator

Deterministic state machine (one per job), worker pool with FOR UPDATE SKIP LOCKED claims and leases, budgets, retries, backtracking and routing of failures to the owning agent.

Status: built: `run.py` (three stages, resumable), `worker.py` (claims, heartbeats, checkpoints, review pause, budgets), `promote.py`, `caps.py`, `events.py` (every ledger "log" event carries `stage`, `attempt`, `visit`, `actor`, `kind` and `detail` next to its unchanged text `line`, so the UI never parses the text; the metadata never drives a transition). See [docs/design.md](../../../docs/design.md), section "Orchestrator state machine".
