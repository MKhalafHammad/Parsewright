# Build log

One entry per completed phase, appended at the end of the phase (see CLAUDE.md, "Build log and demo moments"). Phases and status: [build-plan.md](build-plan.md).

## 2026-10-27 — Phase 0: Repository foundation

**Built**
- Project rules and docs: `CLAUDE.md` (root, `engine/`, `web/`), README, SECURITY.md, MIT LICENSE, `docs/design.md`, threat-model skeleton, six subagent definitions in `.claude/agents/`.
- Public-repo safety:
  - `.gitignore`;
  - `.env.example` with placeholders only;
  - `.claude/settings.json` with attribution off and deny rules;
  - pre-commit with gitleaks, file checks and ruff;
  - a commit-msg hook that rejects AI attribution (`scripts/check_commit_msg.py`).
- Tooling:
  - `Makefile` (`setup`, `up`, `down`, `logs`, `test`, `lint`, `security`);
  - `docker-compose.yml` with Splunk Enterprise 10.6.1 and PostgreSQL 17, where only Splunk Web is published, on 127.0.0.1;
  - CI on pull requests: lint, tests, bandit, semgrep, pip-audit, npm audit, gitleaks over full history.
- Empty package skeleton `engine/parsewright/`, one README per module.

**Test results**
- `make test`: 8/8 passed (commit-msg hook). `make lint`: all hooks passed.
- The hook was also tested end to end in a scratch repo:
  - `Co-Authored-By: Claude` was rejected and no commit was created;
  - an editor-style message with comment lines was accepted.
- CI:
  - the first two runs failed. `splunk-sdk>=3.0` needs Python 3.13, fixed in `42499d1`. Then semgrep blocked mutable GitHub Action tags, fixed by pinning to commit SHAs in `02a1261`.
  - run 4 passed on the final head;
  - merged as PR #1 (`915edcc`).

**Cut or deferred**
- `engine/` and `web/` Dockerfiles, and the Next.js scaffold: the services sit behind the Compose `app` profile until there is code to run.
- semgrep could not run in the build environment (network policy), so its first real run was in CI.
- Docker images pinned by tag, not digest; Python dependencies have lower bounds only, without hashes. Both are tracked as T9.3 and T9.6 in the threat model.
- CI triggers changed from every push to pull requests only (`54f3da4`).

## 2026-10-27 — Phase 1: Threat model and lab verification

**Built**
- `docs/threat-model.md`: assets, trust boundaries, threats per area mapped to guardrails and phases, and residual risks R1–R8.
  - Reviewed twice by `appsec`. The second review found one High: the shared test index removed per-job search scoping, fixed by a code-owned base search (T1.2).
  - All findings are fixed or recorded; new threats T5.8 and T5.9 were added.
- Three read-only lab probes, all run through `scripts/probe.sh llm|splunk|install`. None prints a token.
  - `probe_llm`: structured-output mode and token cost.
  - `probe_splunk`: token scopes, search limits, the `receivers/simple` ingest path.
  - `probe_install`: add-on install and update, index-time settings after install, the deploy role's capabilities.
- All 10 questions in `docs/lab-findings.md` answered with probe output or a recorded decision, and dated notes added to `design.md`. Key outcomes:
  - **Agents:** `response_format` with a strict JSON schema; the model reasons, so output caps need headroom. Standard mode, not contributor mode. Four agents.
  - **Deploy and ingest:** each attempt installs the full `.tgz` through `apps/local`, and `update=true` is a full replace. A new sourcetype's index-time settings apply on the next `receivers/simple` ingest with no reload.
  - **Splunk accounts:** one shared `pw_test` index with a sourcetype per job and attempt. The deploy role is `admin_all_objects`, `edit_tcp`, `install_apps`.
  - **Scope and checks:** in-scope edge cases fixed (Q4). `btool` replaced by an allowlist plus a fail-closed post-install warning check.

**Test results**
- `pytest`: 44/44 passed. pre-commit (ruff, gitleaks, file checks) clean on all files. bandit and pip-audit clean. gitleaks over full history: no leaks in 15 commits.
- Lab: all three probes pass against the owner's standalone Splunk Enterprise and the Meta Model API. The search token cannot install apps or see non-`pw_` indexes.
- All three probes re-run after the appsec fixes: PASS.
- The probes caught two setup errors:
  - a deploy token pasted twice into `.env`, reported as "5 parts, expected 3";
  - a missing `edit_tcp` capability, reported as a 403 on ingest.

**Cut or deferred**
- semgrep is not installed locally; it runs in CI on the PR.
- GitHub branch protection on `main` was skipped by the owner. Default branch and private vulnerability reporting are still to be checked.
- Q3 covered a new sourcetype only, not changed settings on an existing one. This is avoided by design: every attempt gets a new sourcetype.
- `make` is not installed on the lab host, so the `make` steps were run by hand.

**RECORD THIS**
- None. Groundwork, as planned.
