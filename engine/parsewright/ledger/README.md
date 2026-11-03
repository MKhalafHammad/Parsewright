# ledger

PostgreSQL models for the job queue and the append-only run ledger, written on every state transition.

Status: built: `migrations/` (001 jobs and ledger, 002 final states and the limited app role, 003–004 the TA registry), `store.py` (queue, leases, guarded transitions, append-only ledger with NOTIFY, usage, kill switch, advisory locks). See [docs/design.md](../../../docs/design.md), section "Concurrency and continuous operation".
