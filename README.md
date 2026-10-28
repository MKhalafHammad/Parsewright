# Parsewright

From raw sample logs to a tested, CIM-compliant Splunk add-on, verified by Splunk rather than by the model.

[![CI](https://github.com/MKhalafHammad/Parsewright/actions/workflows/ci.yml/badge.svg)](https://github.com/MKhalafHammad/Parsewright/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> **Status:** early development. This README separates what is **built** from what is **planned**. Right now the repository holds a working CLI that builds a TA through all three stages (index-time, extraction, CIM mapping), each checked by a real Splunk, on JSON, key=value, syslog and CSV logs (Phases 2–3). The job queue, the web UI and promotion are planned.

## Demo

- Demo video: _planned (link added at submission)_
- Screenshot: _planned_

## What it does

**The problem.** Every new data source in a SOC needs a parser. Someone has to work out line breaking, timestamps, field extractions and CIM mapping. Writing and testing `props.conf` and `transforms.conf` by hand takes hours per source, and index-time mistakes corrupt data permanently.

**The solution.** You give Parsewright sample logs from one source. A team of Muse Spark agents studies them and writes the Splunk add-on (TA) one stage at a time. Parsewright deploys each attempt to a standalone Splunk Enterprise instance and ingests the samples into a throwaway test index. Fixed Splunk searches then check the result. When a check fails, the owning agent gets the evidence and tries again. When everything passes, a human reviews raw vs parsed events and approves. The result is a `TA-parsewright-<vendor>-<product>.tgz`.

## How it works

The guiding principle is **agents propose, code acts, Splunk judges**:

- **Agents propose.** Muse Spark agents only reason and return schema-validated config proposals. They can run read-only searches, but they never deploy anything.
- **Code acts.** A deterministic orchestrator (a state machine, not an AI manager) gates every proposal through guardrails, then deploys and ingests.
- **Splunk judges.** A Validator made of code and fixed SPL, with no AI, decides pass or fail. Agents never grade themselves.

```
 samples ──► Profiler ──► [human: profile review]
                │
                ▼
      ┌──► Index-time agent ──► guardrails ──► deploy + ingest ──► Validator (SPL) ─┐
      │    Extraction agent        (code)        (pw_* test index)    pass? next   │
      │    CIM mapper agent                                            fail? retry  │
      └──────────────────────────── evidence (expected vs actual) ◄────────────────┘
                │
                ▼
     [human: approve] ──► TA-parsewright-<vendor>-<product>.tgz
```

Each stage retries at most 5 times within a token and time budget. If the budget runs out, the run stops with an honest report of what it could not solve. The full design is in [docs/design.md](docs/design.md).

## Meta models used

| Model | Used for |
| --- | --- |
| Muse Spark (`muse-spark-1.3`, standard mode) via the Meta Model API | All agent reasoning: profiling, index-time settings, field extraction, CIM mapping |
| Muse Spark Open | **On-prem mode**: the same code with a different `LLM_BASE_URL`, so logs never leave your network |
| Muse Code | Speeding up development of this project |

The model is set only through environment variables (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`), never in code.

## Features

| Feature | Status |
| --- | --- |
| Repository foundation: CI, secret scanning, commit hooks, Docker stack (Splunk + PostgreSQL) | **Built** |
| Threat model and lab probes for the Meta Model API and Splunk ([docs/lab-findings.md](docs/lab-findings.md)) | **Built** (all lab questions answered) |
| Synthetic log generator with truth manifests (JSON, key=value, syslog, CSV) | **Built** |
| Profiler agent | **Built** (profile review is auto-approved; the human review screen is planned) |
| Index-time agent with a retry loop fed by Validator evidence | **Built** |
| Extraction and CIM mapper agents with retry loops, regression re-runs and one backtrack | **Built** |
| Guardrails: stage gates plus a final gate over the whole package (allowlisted keys after Unicode normalisation, no forbidden keys, no foreign stanzas, eventtype anchoring, CIM provenance, environment-independent EVALs), with an adversarial suite of 90+ attacks | **Built** |
| Validator: index-time checks (event count, timestamp accuracy, parser warnings) | **Built** |
| Validator: extraction and CIM checks (Authentication, Network_Traffic, Web) with the three-number CIM score | **Built** |
| TA builder: escaping conf writer, test identity, reproducible `.tgz` packaging with a file allowlist and SHA-256 | **Built** |
| Approval and promotion: `parsewright approve <job> --sha256 …` (hash-bound, replay-safe), `parsewright promote <job>` (deterministic rename to real names, both hashes linked, refuses existing TAs and sourcetypes, smoke test) | **Built** |
| CLI: `parsewright run <file>` (all three stages) | **Built** |
| Web UI (Next.js): job board with upload, live run view, profile review, approval report (raw vs parsed with highlights, mapping, CIM scores, configs, approve/reject, `.tgz` download) | **Built** |
| Parallel jobs: PostgreSQL queue (`FOR UPDATE SKIP LOCKED`, leases, heartbeats, crash resume), append-only ledger, worker pool with a global Splunk-write lock, LLM slots, daily token budget and kill switch | **Built** |
| HTTP API: upload (content checks, duplicates), runs, profile review, approve/reject, `.tgz` download, live server-sent events; `parsewright serve` | **Built** (no login: localhost only, residual risk R1) |
| Routing for shared syslog feeds | Planned (stretch) |
| Parser updates and drift monitoring | Planned (stretch) |

## Prerequisites

- **OS:** Linux or macOS. On Windows, use WSL2.
- **Docker Engine 24+** with **Docker Compose v2.20+** (`docker compose version`).
- **Memory and disk for Splunk:** at least 8 GB of RAM free for Docker (4 GB is the bare minimum), and at least 20 GB of free disk. Splunk pauses indexing when free disk drops below 5 GB.
- **Architecture:** the Splunk image is x86-64. On Apple Silicon it runs under emulation and is slower.
- **A Meta Model API key** (needed once the engine is built).
- For development: Python 3.12+, `make`, plus [gitleaks](https://github.com/gitleaks/gitleaks) and [semgrep](https://semgrep.dev/) for `make security`.

## Quick start

1. Clone the repository:
   ```bash
   git clone https://github.com/MKhalafHammad/Parsewright.git
   cd Parsewright
   ```
2. Create your environment file:
   ```bash
   cp .env.example .env
   ```
3. Fill in `.env`. Replace every placeholder; never commit this file.

   | Variable | Required | Description | Example placeholder |
   | --- | --- | --- | --- |
   | `LLM_API_KEY` | Yes (CLI) | Meta Model API key | `your-meta-api-key-here` |
   | `LLM_BASE_URL` | Yes | OpenAI-compatible endpoint | `https://api.meta.ai/v1` |
   | `LLM_MODEL` | Yes | Model name | `muse-spark-1.3` |
   | `SPLUNK_START_ARGS` | Yes | Accepts the Splunk license | `--accept-license` |
   | `SPLUNK_GENERAL_TERMS` | Yes | Accepts the Splunk General Terms (Splunk 10.x) | `--accept-sgt-current-at-splunk-com` |
   | `SPLUNK_PASSWORD` | Yes | Splunk `admin` password, 8+ characters | `changeme-to-a-long-password` |
   | `SPLUNK_WEB_PORT` | No | Host port for Splunk Web (default 8000) | `8000` |
   | `SPLUNK_HOST` | Yes (engine, CLI, probes) | Splunk REST host (`splunk` inside Docker) | `splunk.example.com` |
   | `SPLUNK_PORT` | Yes | Splunk REST port | `8089` |
   | `SPLUNK_SEARCH_TOKEN` | Yes (CLI) | Token for the search-only service account | `your-parsewright-search-token-here` |
   | `SPLUNK_DEPLOY_TOKEN` | Yes (CLI) | Token for the deploy service account | `your-parsewright-deploy-token-here` |
   | `SPLUNK_DRIFT_TOKEN` | Yes (engine, planned) | Token for the drift read-only account | `your-parsewright-drift-token-here` |
   | `PARSEWRIGHT_PACKAGES_DIR` | Yes (CLI) | Folder for `.tgz` packages, readable by splunkd, owned by you, mode 755 | `/opt/parsewright/packages` |
   | `PARSEWRIGHT_TEST_INDEX` | Yes (CLI) | The one shared test index; must start with `pw_` | `pw_test` |
   | `PARSEWRIGHT_RUN_TOKEN_CEILING` | No | Token ceiling per run (default 300000) | `300000` |
   | `POSTGRES_DB` | Yes | Database name | `parsewright` |
   | `POSTGRES_USER` | Yes | Database user | `parsewright` |
   | `POSTGRES_PASSWORD` | Yes | Database password | `changeme-to-a-long-password` |
   | `WEB_PORT` | No | Host port for the web UI (default 3000) | `3000` |

4. Install the dev tooling and start the stack:
   ```bash
   make setup
   make up
   ```
   `make up` currently starts Splunk and PostgreSQL. The engine and web services are defined behind the `app` profile and start once their code exists (planned).
5. Open the UIs:
   - Splunk Web: http://localhost:8000. Log in as `admin` with your `SPLUNK_PASSWORD`. The first start takes a few minutes.
   - Parsewright UI: http://localhost:3000
6. Run a first job with the bundled synthetic sample (index-time stage):
   ```bash
   .venv/bin/parsewright run engine/parsewright/generator/fixtures/acme_vpn.json --vendor acme --product vpn
   ```
   It profiles the log, then runs three stages (index-time, extraction, CIM mapping). Each stage installs the add-on under its test identity, and the Validator checks it in Splunk, retrying with evidence up to 5 times. It ends with the holdout line and the three CIM numbers per data model, for example `CIM Authentication: required fields 4/4 passed, available fields mapped 4/4, not in source 2`. Other fixtures: `demo/02_cim_green.sh vpn|fw|ssh|proxy`. Options: `--tz` (logs' timezone), `--keep` (leave the test add-on installed), `--stages`.

## Configuration

Every setting lives in `.env`. [.env.example](.env.example) documents each variable: what it is, whether it is required and where to get it. Docker Compose reads `.env` and refuses to start if a required value is missing.

**Using a self-hosted Muse Spark Open (on-prem mode).** Run Muse Spark Open behind an OpenAI-compatible endpoint inside your network. Then point Parsewright at it:

```bash
LLM_BASE_URL=https://llm.example.com/v1
LLM_MODEL=<model name your server exposes>
LLM_API_KEY=<key your server expects, or any placeholder if none>
```

Nothing else changes, and sample logs never leave your network.

## Usage

_Planned. This describes the intended flow from the design._

**Web UI**
1. **New run:** upload sample logs from one source (JSON, key=value, syslog or CSV; about 50 events to 10 MB). Optionally fill in vendor, timezone and target CIM model.
2. **Profile review:** confirm or correct the detected vendor, timezone, event categories and CIM targets.
3. **Live run view:** watch each stage's attempts, config diffs, check results and evidence.
4. **Approval report:** compare raw and parsed events side by side, review the field → CIM mapping table and scores, then approve, reject or correct a mapping. Download the `.tgz`.

**CLI**
```bash
parsewright run samples.log
```
This runs the same pipeline headless and prints the report.

## Running tests and security checks

```bash
make test      # pytest (engine and repo tooling)
make lint      # all pre-commit hooks over all files: ruff, gitleaks, file checks
make security  # bandit, semgrep, pip-audit, npm audit, gitleaks over full git history
```

`make security` needs `gitleaks` and `semgrep` on your PATH:

```bash
brew install gitleaks          # or: go install github.com/zricethezav/gitleaks/v8@v8.30.1
pipx install semgrep           # kept out of the project venv to avoid dependency clashes
```

CI runs `make lint`, `make test` and `make security` on every pull request (not on plain branch pushes). Any failure fails the build.

## Security

- Report vulnerabilities privately; see [SECURITY.md](SECURITY.md).
- `.env` is git-ignored and never committed. gitleaks scans every commit and the full history in CI.
- **Do not upload real production logs to a hosted model.** Use the synthetic generator, mask your data, or use on-prem mode with Muse Spark Open.
- **Guardrails** (see [docs/design.md](docs/design.md), "Guardrails and security"):
  - Agents cannot deploy. Every proposal passes a deterministic gate with a key allowlist and value checks. That gate blocks `nullQueue`, index rerouting, `INGEST_EVAL`/`SEDCMD`, `[default]` stanzas and newline injection, and runs `btool check` and a regex backtracking test.
  - Test deploys use separate app and sourcetype names and `pw_*` indexes only.
  - Approval is bound to the SHA-256 of the exact `.tgz`.
  - Logs are treated as data, never as instructions.

## Project structure

```
.
├── engine/                  Python backend (package: parsewright)
│   ├── parsewright/
│   │   ├── api/             FastAPI routes, upload checks and the SSE stream (built)
│   │   ├── orchestrator/    three-stage run loop, workers, approval and promotion (built)
│   │   ├── agents/          LLM client, Profiler, Index-time, Extraction, CIM mapper (built)
│   │   ├── tools/           lab probes, Splunk client, search guard, test_regex (built)
│   │   ├── guardrails/      index-time and search-time gates (built); full adversarial suite (planned)
│   │   ├── validator/       index-time, extraction and CIM checks (built)
│   │   ├── ta_builder/      escaping conf writer, naming, .tgz packaging (built)
│   │   ├── ledger/          PostgreSQL job queue and append-only ledger (built)
│   │   ├── cim_spec/        CIM 8.7.0 required fields and allowed values, pinned from Splunk_SA_CIM (built)
│   │   └── generator/       synthetic logs in four formats + truth manifests; fixtures/ (built)
│   └── tests/               engine tests
├── web/                     Next.js + shadcn/ui UI (built)
├── docs/                    design.md (source of truth), build-plan.md, threat-model.md, lab-findings.md
├── scripts/                 repo tooling (commit-msg hook)
├── tests/                   repo tooling tests
├── .claude/                 project settings and subagents for Claude Code
├── .github/workflows/       CI
├── docker-compose.yml       Splunk Enterprise, PostgreSQL, engine, web
├── Makefile                 setup, up, down, logs, test, lint, security
└── .env.example             every variable, placeholders only
```

## Troubleshooting

- **Splunk is slow to start.** The first start takes several minutes while the container provisions itself. Follow it with `make logs` (or `docker compose logs -f splunk`). Wait for `docker compose ps` to show `healthy`.
- **Splunk exits right away mentioning the license or general terms.** `SPLUNK_START_ARGS=--accept-license` and `SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com` must both be set in `.env`. Setting them means you accept the Splunk license and terms.
- **Splunk rejects the admin password.** `SPLUNK_PASSWORD` needs at least 8 characters. If you change it after the first start, the old password stays in the `splunk-etc` volume. Run `docker compose down -v` to reset, which **deletes all Splunk and PostgreSQL data**.
- **Port already in use.** Change `SPLUNK_WEB_PORT` or `WEB_PORT` in `.env`, then run `make down && make up`.
- **`required variable ... is missing a value`.** A required `.env` value is empty or missing. Compare your `.env` with `.env.example`.
- **Meta API errors** (planned engine):
  - 401/403: check `LLM_API_KEY`.
  - 404: check `LLM_BASE_URL` and `LLM_MODEL`.
  - 429: you hit a rate limit or used up your credits. Check the spend limit on your Meta billing page.

## Hackathon note

Parsewright is being built during the **Meta Global AI Developer Hackathon** (building period Oct 27 – Nov 4, 2026), "Build for Your World" track. All code in this repository is written during the event, starting with the first commit on Oct 27, 2026. Only synthetic logs are used. The demo will show only features built during the event.

Built so far: the project foundation, the threat model and the lab probes. Progress per phase is tracked in the Status table of [docs/build-plan.md](docs/build-plan.md).

## Limitations and roadmap

**Hackathon scope:**
- One standalone Splunk Enterprise instance.
- Four formats: JSON, key=value, syslog, CSV.
- Three CIM data models: Authentication, Network_Traffic, Web.

**Out of scope for now:**
- Splunk Cloud, clusters and forwarders.
- Writing `inputs.conf`.
- XML and binary formats.
- Updating TAs that Parsewright did not build.

**Roadmap (after the core loop):**
- Routing for shared syslog feeds.
- Parser updates with old and new format regression.
- Drift monitoring with automatic update jobs.
- A `pw_audit` index and dashboard.
- Login with an approver role.
- Pinned dependencies with hashes.

See [docs/design.md](docs/design.md) for details and open questions.

## License

[MIT](LICENSE) © 2026 Mohamed K. Hammad
