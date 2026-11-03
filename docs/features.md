# Features

What is built and what is planned. The README summarises this table.

| Feature | Status |
| --- | --- |
| Repository foundation: CI, secret scanning, commit hooks | **Built** |
| One-command Docker stack (`make up`): Splunk, PostgreSQL, engine and UI; Splunk prepared automatically (test index, least-privilege roles and tokens, CIM add-on and macros) | **Built** (clean-machine test pending) |
| Threat model and lab probes for the Meta Model API and Splunk ([docs/lab-findings.md](lab-findings.md)) | **Built** (all lab questions answered) |
| Synthetic log generator with truth manifests (JSON, key=value, syslog, CSV) | **Built** |
| Profiler agent, with a human profile review in the UI (or skipped per run) | **Built** |
| Index-time agent with a retry loop fed by Validator evidence | **Built** |
| Extraction and CIM mapper agents with retry loops, regression re-runs and one backtrack | **Built** |
| Guardrails: stage gates plus a final gate over the whole package (allowlisted keys after Unicode normalisation, no forbidden keys, no foreign stanzas, eventtype anchoring, CIM provenance, environment-independent EVALs), with an adversarial suite of 87 tests | **Built** |
| Validator: index-time checks (event count, timestamp accuracy, fallback, parser warnings, `TIME_FORMAT` really matching every event) | **Built** |
| Validator: extraction and CIM checks (Authentication, Network_Traffic, Web) with the three-number CIM score | **Built** |
| Logs without a truth manifest: upload just the log. Generator samples are recognised and checked against their known answers; any other log is checked mechanically on every event (each time equal to the time written in its line, read by code; every value exactly as written in its line; CIM gaming rules), the run asks a human for the timezone only when the timestamps carry none, and the approval report lists the agents' decisions (timestamp reading, field meanings, value → CIM value with counts) | **Built** |
| TA builder: escaping conf writer, test identity, reproducible `.tgz` packaging with a file allowlist and SHA-256 | **Built** |
| Approval and promotion: `parsewright approve <job> --sha256 …` (hash-bound, replay-safe), `parsewright promote <job>` (deterministic rename to real names, both hashes linked, refuses existing TAs and sourcetypes, smoke test) | **Built** |
| CLI: `parsewright run <file>` (all three stages) | **Built** |
| Web UI (Next.js): runs board with "Needs you" and a new-run sheet; run workspace with a clickable, deep-linkable phase rail, every attempt's proposal, gate verdict and Splunk checks, and a live activity feed showing which agent is acting; profile review; approval report (raw vs parsed with field colours and a CIM view, readable config and row diffs, approve/reject, `.tgz` download); TA registry | **Built** |
| Parallel jobs: PostgreSQL queue (`FOR UPDATE SKIP LOCKED`, leases, heartbeats, crash resume), append-only ledger, worker pool with a global Splunk-write lock, LLM slots, daily token budget and kill switch | **Built** |
| HTTP API: upload (content checks, duplicates), runs, profile review, approve/reject, `.tgz` download, live server-sent events; `parsewright serve` | **Built** (no login: localhost only, residual risk R1) |
| Routing for shared syslog feeds | Planned (stretch) |
| Parser updates: TA registry (versions, samples, baseline); `parsewright update <TA> <file>` or the upload form; Diagnose with no model call (0 tokens if the TA already parses the new format); only failing stages patched; every attempt checked on the old and the new samples; diff against production and `local/` override flags in the review; in-place promotion with a version bump that keeps `local/`; exact-version `parsewright rollback` | **Built** |
| Drift monitoring with automatic update jobs | Planned (stretch) |
| Drop folder intake (a watched folder, one job per subfolder) | Planned (the symlink-refusing intake helper is built) |
| Correcting a mapping from the approval report, sent back to the owning stage as evidence | Planned |
| Login with an approver role | Planned (localhost only today, residual risk R1) |
| Secret scan and masking of uploaded samples | Planned (use synthetic logs or on-prem mode) |
| A `pw_audit` index and dashboard for agent activity | Planned |
