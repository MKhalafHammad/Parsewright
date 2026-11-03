# Setup, configuration and operations

The README has the short version. This page has every detail: what you need, each setup step, running without Docker, configuration, the CLI, tests, the project layout and troubleshooting.

## Prerequisites

- **OS:** Linux or macOS. On Windows, use WSL2.
- **Docker Engine 24+** with **Docker Compose v2.20+** (`docker compose version`).
- **Memory and disk for Splunk:** at least 8 GB of RAM free for Docker (4 GB is the bare minimum), and at least 30 GB of free disk (35 GB recommended): the images, Splunk's data and the builds. Splunk pauses indexing when free disk drops below 5 GB.
- **Architecture:** the Splunk image is x86-64. On Apple Silicon it runs under emulation and is slower.
- **`make` and Python 3.10+** on the host (the setup scripts use the standard library only).
- **A Meta Model API key.**
- **The Splunk Common Information Model add-on** `.tgz` from Splunkbase (free account; it is licensed by Splunk, so it is not bundled). See [lab/README.md](../lab/README.md).
- For development: Python 3.12+ and Node 24, plus [gitleaks](https://github.com/gitleaks/gitleaks) and [semgrep](https://semgrep.dev/) for `make security`.

## Quick start

About 15 minutes on a fresh machine, most of it Splunk's first start.

1. Clone the repository:
   ```bash
   git clone https://github.com/MKhalafHammad/Parsewright.git
   cd Parsewright
   ```
2. Create `.env` and put your Meta Model API key in it:
   ```bash
   make env        # creates .env from .env.example and generates every password
   ```
   Then edit `.env` and set `LLM_API_KEY`. Nothing else needs a value: the passwords are generated, and the Splunk tokens are created in step 4. Never commit `.env`.
3. Put the CIM add-on in `lab/`: download "Splunk Common Information Model (CIM)" from Splunkbase and save the `.tgz` there, keeping its name ([lab/README.md](../lab/README.md)).
4. Start everything:
   ```bash
   make up         # DOCKER="sudo docker" make up   if your user cannot reach Docker
   ```
   Always start the stack with `make up`, not `docker compose up` directly: `make up` replaces the placeholder passwords first. It starts Splunk and PostgreSQL, then prepares Splunk inside its own container: the `pw_test` index, three service accounts with least-privilege roles (search, deploy, drift), the CIM add-on with its index macros pointed at `pw_*`, and one fresh token per account, written into `.env` and never printed. Then it starts the engine and the web UI. Every port is bound to `127.0.0.1`.
5. Start the first run with the bundled synthetic VPN log:
   ```bash
   make first-run
   ```
   It prints the run's page. Open http://localhost:3000 and watch the agents work: Profiler, then Index-time, Extraction and CIM mapping, each attempt checked in Splunk. When it reaches "Awaiting approval", review raw vs parsed and the configuration, then approve or download the `.tgz`.

Splunk Web is at http://localhost:8000 (user `admin`, password `SPLUNK_PASSWORD` from `.env`). `make down` stops the stack; `docker compose down -v` also deletes its data.

**Without Docker, against your own Splunk** (the lab setup): follow [docs/lab-findings.md](lab-findings.md), "Lab setup", set `SPLUNK_HOST`, `SPLUNK_PORT` and the three tokens in `.env`, then `make setup` and `.venv/bin/parsewright serve`.

## Configuration

Every setting lives in `.env`. [.env.example](../.env.example) documents each variable: what it is, whether it is required and where to get it. Docker Compose reads `.env` and refuses to start if a required value is missing.

**Using a self-hosted Muse Spark Open (on-prem mode).** Run Muse Spark Open behind an OpenAI-compatible endpoint inside your network. Then point Parsewright at it:

```bash
LLM_BASE_URL=https://llm.example.com/v1
LLM_MODEL=<model name your server exposes>
LLM_API_KEY=<key your server expects, or any placeholder if none>
```

Nothing else changes, and sample logs never leave your network.

**Opening the UI from another machine.** Docker binds every port to `127.0.0.1`, so the UI is reachable only on the machine running it. To use it from another machine, the simplest way is an SSH tunnel from that machine: `ssh -L 3000:localhost:3000 <user>@<server>`, then open http://localhost:3000. To serve it on the network instead (outside Docker), start the UI with `HOSTNAME=0.0.0.0` (set it explicitly: shells often set `HOSTNAME` to the machine's name) and add the server's address to `ALLOWED_HOSTS` and `WEB_ORIGINS` (see the note at the end of [.env.example](../.env.example)), then open the port in the server's firewall. With firewalld, `sudo firewall-cmd --add-port=3000/tcp --permanent` changes only the saved rules: run `sudo firewall-cmd --reload` to apply them.

## Usage

**Web UI** (http://localhost:3000)
1. **New run:** upload a sample log from one source (JSON, key=value, syslog or CSV; at least 50 events, at most 10 MB). That is all that is needed; vendor, product and timezone are optional. Or choose a promoted TA to update it for a new log format.
2. **Profile review:** confirm or correct what the Profiler found (vendor, product, sourcetype, timezone), with field coverage shown. Skippable, except when the timestamps carry no timezone and none was given: nothing in the file can prove which zone they are in, so the run asks.
3. **Run workspace:** the "Now" banner names the agent at work; the phase rail opens any phase and attempt (`/runs/<job>?phase=extraction&attempt=2`). Each attempt shows the proposal, the guardrail gate's verdict, Splunk's checks (expected vs actual, failing events) and what changed since the previous attempt. The activity feed is grouped by phase and attempt.
4. **Approval report:** CIM scores, attempts per phase and holdout; how the run was validated (against known answers, or mechanically); the decisions the agents made (how the timestamp is read, with the first event's result; field meanings; each source value → CIM value with its count), which are what you vouch for when you approve; raw vs parsed with one colour per field and a CIM view; the configuration as the `.conf` files themselves. Approve (bound to the package's SHA-256, with a second confirmation), reject, or download the `.tgz`.

**CLI**
```bash
.venv/bin/parsewright run engine/parsewright/generator/fixtures/acme_vpn.json --vendor acme --product vpn
.venv/bin/parsewright update TA-parsewright-acme-fw new_format.log
.venv/bin/parsewright approve <job> --sha256 <hash> && .venv/bin/parsewright promote <job>
```
The CLI runs the same pipeline headless against the Splunk in `.env` and prints each attempt, check and the CIM score.

## Running tests and security checks

```bash
make test      # pytest (engine and repo tooling), then the web build and Playwright end-to-end tests
make lint      # all pre-commit hooks (ruff, gitleaks, file checks), then ESLint and TypeScript
make security  # bandit, semgrep, pip-audit, npm audit, gitleaks over full git history
```

`make security` needs `gitleaks` and `semgrep` on your PATH:

```bash
brew install gitleaks          # or: go install github.com/zricethezav/gitleaks/v8@v8.30.1
pipx install semgrep           # kept out of the project venv to avoid dependency clashes
```

CI runs `make lint`, `make test` and `make security` on every pull request (not on plain branch pushes). Any failure fails the build.

## Project structure

```
.
├── engine/                  Python backend (package: parsewright)
│   ├── parsewright/
│   │   ├── api/             FastAPI routes, upload checks and the SSE stream (built)
│   │   ├── orchestrator/    three-stage run loop, workers, approval and promotion (built)
│   │   ├── agents/          LLM client, Profiler, Index-time, Extraction, CIM mapper (built)
│   │   ├── tools/           lab probes, Splunk client, search guard, test_regex (built)
│   │   ├── guardrails/      index-time and search-time gates, final package gate, adversarial suite (built)
│   │   ├── validator/       index-time, extraction and CIM checks (built)
│   │   ├── ta_builder/      escaping conf writer, naming, .tgz packaging (built)
│   │   ├── ledger/          PostgreSQL job queue and append-only ledger (built)
│   │   ├── cim_spec/        CIM 8.7.0 required fields and allowed values, pinned from Splunk_SA_CIM (built)
│   │   └── generator/       synthetic logs in four formats + truth manifests; fixtures/ (built)
│   └── tests/               engine tests
├── web/                     Next.js + shadcn/ui UI (built)
├── docs/                    design.md (source of truth), setup.md, features.md, threat-model.md,
│                            lab-findings.md, build-plan.md, build-log.md, demo-script.md
├── scripts/                 one-command setup (up.sh, Splunk bootstrap), first run, commit-msg hook
├── lab/                     licensed add-ons you download (CIM); git-ignored packages
├── demo/                    repeatable scripts for each demo moment
├── tests/                   repo tooling tests
├── .claude/                 project settings and subagents for Claude Code
├── .github/workflows/       CI
├── docker-compose.yml       Splunk Enterprise, PostgreSQL, engine, web
├── Makefile                 env, up, first-run, down, logs, setup, test, lint, security
└── .env.example             every variable, placeholders only
```

## Troubleshooting

- **Splunk is slow to start.** The first start takes several minutes while the container provisions itself. Follow it with `make logs` (or `docker compose logs -f splunk`). Wait for `docker compose ps` to show `healthy`.
- **Splunk exits right away mentioning the license or general terms.** `SPLUNK_START_ARGS=--accept-license` and `SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com` must both be set in `.env`. Setting them means you accept the Splunk license and terms.
- **Splunk rejects the admin password.** `SPLUNK_PASSWORD` needs at least 8 characters. If you change it after the first start, the old password stays in the `splunk-etc` volume. Run `docker compose down -v` to reset, which **deletes all Splunk and PostgreSQL data**.
- **Port already in use.** Change `SPLUNK_WEB_PORT` or `WEB_PORT` in `.env`, then run `make down && make up`.
- **`required variable ... is missing a value`.** A required `.env` value is empty or missing. Compare your `.env` with `.env.example`.
- **`make up` stops at "preparing Splunk" with "no package is in lab/".** Download the CIM add-on into `lab/` (step 3), then run `make up` again; every step is safe to repeat.
- **The engine logs 401 from Splunk.** The service tokens last 7 days. Run `make up` again: it replaces all three.
- **Meta API errors:**
  - 401/403: check `LLM_API_KEY`.
  - 404: check `LLM_BASE_URL` and `LLM_MODEL`.
  - 429: you hit a rate limit or used up your credits. Check the spend limit on your Meta billing page.
