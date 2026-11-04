# Setup

Every step from an empty machine to an approved add-on, then configuration, usage, tests and troubleshooting. These steps were tested on a fresh Ubuntu 26.04 VM. The commands are for Ubuntu; on other systems, install the same tools your usual way.

**Contents**

- [What you need](#what-you-need)
- [Step 1: Install the tools](#step-1-install-the-tools)
- [Step 2: Let your user run Docker](#step-2-let-your-user-run-docker)
- [Step 3: Get the code and create `.env`](#step-3-get-the-code-and-create-env)
- [Step 4: Add the Splunk CIM add-on](#step-4-add-the-splunk-cim-add-on)
- [Step 5: Start everything](#step-5-start-everything)
- [Step 6: Start the first run](#step-6-start-the-first-run)
- [Step 7: Review and approve](#step-7-review-and-approve)
- [Messages that are safe to ignore](#messages-that-are-safe-to-ignore)
- [Stop, restart or reset](#stop-restart-or-reset)
- [Configuration](#configuration)
- [Usage](#usage)
- [Running tests and security checks](#running-tests-and-security-checks)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)

## What you need

| Item | Requirement |
| --- | --- |
| Operating system | Linux or macOS. On Windows, use WSL2 |
| CPU | x86-64, 4 cores recommended. The Splunk image is x86-64, so on Apple Silicon it runs under emulation and is slower |
| Memory | At least 8 GB of RAM free for Docker (4 GB is the bare minimum) |
| Disk | At least 40 GB free, for the images, Splunk's data and the builds. Splunk pauses indexing when free disk drops below 5 GB |
| Tools | Docker Engine 24+, Docker Compose v2.20+, `git`, `make`, `curl`, Python 3.10+ ([Step 1](#step-1-install-the-tools)) |
| Meta Model API key | From your Meta developer account. One run uses about 50k tokens |
| Splunkbase account | Free, to download the CIM add-on ([Step 4](#step-4-add-the-splunk-cim-add-on)) |
| Internet access | To download the images and to reach the Meta Model API |

For development you also need Python 3.12+ and Node 24, plus [gitleaks](https://github.com/gitleaks/gitleaks) and [semgrep](https://semgrep.dev/) for `make security`.

If you added disk to a VM, check that the system can use it: `df -h /` should show the new size.

## Step 1: Install the tools

Skip this step if `docker --version` and `docker compose version` already show the versions above.

```bash
sudo apt update
sudo apt install -y git make python3 curl
curl -fsSL https://get.docker.com | sudo sh
```

For other systems, see [Install Docker Engine](https://docs.docker.com/engine/install/); on macOS or Windows, Docker Desktop includes Compose.

Check the versions:

```bash
docker --version          # 24 or later
docker compose version    # v2.20 or later
python3 --version         # 3.10 or later
```

## Step 2: Let your user run Docker

Run this once, then **log out and back in** so the change applies:

```bash
sudo usermod -aG docker $USER
```

Check it with `docker ps`, which must work without `sudo`.

**Why this matters:** the app itself doesn't depend on this group, but every `make` command that calls Docker does. Without it, `make up` stops with `permission denied while trying to connect to the docker API`.

If you can't change the group, use this form of the command in Step 5, which runs only Docker through `sudo`:

```bash
DOCKER="sudo docker" make up
```

`make down` and `make logs` always use plain `docker`, so in that case run `sudo docker compose down` and `sudo docker compose logs -f` instead.

> [!WARNING]
> Never run `sudo make up`. It stops with a message, because running the setup as root would leave `.env` owned by root, and your own commands would then fail with `open .env: permission denied`.

Members of the `docker` group have root-level access to the machine, so add only users you trust.

## Step 3: Get the code and create `.env`

```bash
git clone https://github.com/MKhalafHammad/Parsewright.git
cd Parsewright
make env
```

`make env` creates `.env` and generates every password. **It then ends with an error, and that is expected at this point:**

```text
created .env from .env.example
generated: SPLUNK_PASSWORD, POSTGRES_PASSWORD, POSTGRES_APP_PASSWORD
LLM_API_KEY is still a placeholder: set your Meta Model API key in .env
make: *** [Makefile:18: env] Error 1
```

`.env` was created correctly. The message is only a reminder to add your key, so open `.env` and set it:

```bash
nano .env        # set LLM_API_KEY=<your key>, then save
```

Nothing else needs a value: the passwords are generated, and the Splunk tokens are created in Step 5. Never commit `.env`.

## Step 4: Add the Splunk CIM add-on

The CIM stage checks events against Splunk's Common Information Model data models, so Splunk needs this add-on. It is free, but Splunk licenses it, so it can't be included in this repository.

1. Sign in to Splunkbase with a free account and download [Splunk Common Information Model (CIM)](https://splunkbase.splunk.com/app/1621). Parsewright's checks are pinned to version **8.7.0**.
2. Copy the `.tgz` into `lab/`, keeping its name:
   ```bash
   cp ~/splunk-common-information-model-cim_870.tgz lab/
   chmod 644 lab/*.tgz
   ```
   If you downloaded it on another computer, copy it to the server first:
   ```bash
   scp splunk-common-information-model-cim_870.tgz <user>@<server>:~/Parsewright/lab/
   ```
3. Check that `ls lab/*.tgz` shows exactly one file. It must be a regular file, not a link.

> [!WARNING]
> **If you skip this step, setup stops partway.** `make up` starts Splunk and PostgreSQL, then fails at "preparing Splunk" with:
>
> `FAILED: the CIM add-on is not installed; put exactly one CIM package (a regular file, not a link) in lab/`
>
> The engine and the web UI don't start, and no Splunk tokens are created. To recover, add the file and run `make up` again. You don't need to wipe anything. The same message appears if `lab/` holds two packages.

## Step 5: Start everything

```bash
make up
```

This takes about 15 minutes the first time, mostly Splunk's first start. Always use `make up` rather than `docker compose up`, because it also prepares Splunk:

1. It starts Splunk and PostgreSQL and waits until they are healthy.
2. It creates the `pw_test` index and three least-privilege service accounts (search, deploy, drift).
3. It installs the CIM add-on, restarts Splunk, and points the add-on's index macros at `pw_*`.
4. It creates one fresh token per account and writes them to `.env` without printing them.
5. It builds and starts the engine and the web UI.

Success ends with:

```text
Parsewright is up.
  UI:          http://localhost:3000
  Splunk Web:  http://localhost:8000  (user admin, password SPLUNK_PASSWORD in .env)
First run:     make first-run
```

`make up` is safe to run again at any point, and it continues from where it stopped.

## Step 6: Start the first run

```bash
make first-run
```

This uploads a bundled synthetic VPN log and follows it through the Profiler, Index-time, Extraction and CIM stages, checking each attempt in Splunk. It takes a few minutes, and success ends with:

```text
<job>: awaiting_approval. Open http://localhost:3000/runs/<job> to review and approve.
```

## Step 7: Review and approve

A human approves every add-on before it is promoted, so this last step is yours.

1. Open the run's page from Step 6, or start at http://localhost:3000.
2. Review raw vs parsed events and the configuration.
3. Click **Approve** and confirm.

The run ends as `done`, and the add-on appears in the TA registry.

Splunk Web is at http://localhost:8000 (user `admin`, password `SPLUNK_PASSWORD` from `.env`).

> [!IMPORTANT]
> **The web UI and Splunk Web open only on the machine running Parsewright, not from another machine.** This is a security choice: the UI has no login, so every port is bound to `127.0.0.1`, and the UI accepts only `localhost:3000` and `127.0.0.1:3000`. Use a browser on that same machine.

## Messages that are safe to ignore

| Message | When | Why it's fine |
| --- | --- | --- |
| `LLM_API_KEY is still a placeholder` and `make: *** [Makefile:18: env] Error 1` | `make env`, before you set the key | `.env` was created. Set the key ([Step 3](#step-3-get-the-code-and-create-env)) |
| `unhealthy` in `docker compose ps` | While Splunk starts or restarts | `make up` keeps waiting, and it clears once Splunk is ready. It's a problem only if it lasts more than 15 minutes |
| A failed attempt in a run | During a run | That is the fix loop: Splunk's evidence goes back to the agent, which tries again. Each stage gets up to 5 attempts |
| `(already known)` after the job id | `make first-run` again | The same log already has a run, so the script follows that run instead of starting another |

## Stop, restart or reset

```bash
make down                # stop the stack; all data is kept
make up                  # start it again
make logs                # follow the logs
docker compose down -v   # stop and DELETE all Splunk and PostgreSQL data
```

To start from nothing, run `docker compose down -v`, delete the folder, and go back to [Step 3](#step-3-get-the-code-and-create-env). Save your CIM `.tgz` first.

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

**Serving the UI on the network, outside Docker.** Start the UI with `HOSTNAME=0.0.0.0` (set it explicitly: shells often set `HOSTNAME` to the machine's name) and add the server's address to `ALLOWED_HOSTS` and `WEB_ORIGINS` (see the note at the end of [.env.example](../.env.example)), then open the port in the server's firewall. With firewalld, `sudo firewall-cmd --add-port=3000/tcp --permanent` changes only the saved rules: run `sudo firewall-cmd --reload` to apply them. The UI has no login, so anyone who can reach that port can use it.

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
- **`the KV store is not ready`.** Splunk's tokens need its KV store. `make up` waits 5 minutes for it; run `make up` again, and if it repeats, read `docker compose logs splunk`.
- **Port already in use.** Change `SPLUNK_WEB_PORT` or `WEB_PORT` in `.env`, then run `make down && make up`.
- **`required variable ... is missing a value`.** A required `.env` value is empty or missing. Compare your `.env` with `.env.example`.
- **`FAILED: the CIM add-on is not installed`.** `lab/` has no CIM package, or more than one. See [Step 4](#step-4-add-the-splunk-cim-add-on), then run `make up` again.
- **`permission denied while trying to connect to the docker API`.** Your user can't reach Docker yet. See [Step 2](#step-2-let-your-user-run-docker), and remember to log out and back in.
- **`open .env: permission denied`.** `.env` is owned by root, usually from an older `sudo make up`. Run `sudo chown "$USER":"$USER" .env`.
- **`make first-run` ends with `error`.** Read the reason with `docker compose logs --tail=40 engine`. Running `make first-run` again starts a new run.
- **The engine logs 401 from Splunk.** The service tokens last 7 days. Run `make up` again: it replaces all three.
- **Meta API errors:**
  - 401/403: check `LLM_API_KEY`.
  - 404: check `LLM_BASE_URL` and `LLM_MODEL`.
  - 429: you hit a rate limit or used up your credits. Check the spend limit on your Meta billing page.
