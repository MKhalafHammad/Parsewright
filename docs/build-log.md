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

## 2026-10-27 — Phase 2: Walking skeleton (JSON, CLI, end to end)

**Built**
- **`parsewright run <file>`:** profiles a log, proposes index-time settings, and installs them as a test add-on (`TA-parsewright-<vendor>-<product>__test_<job>`, sourcetype `<st>__test_<job>_a<n>`). It ingests into the shared `pw_test` index and runs the Validator, retrying with evidence up to 5 times.
- **Safety core:**
  - the one escaping conf writer (newlines, continuation backslashes and control characters rejected);
  - naming rules;
  - packaging with a file allowlist, `O_EXCL|O_NOFOLLOW` and SHA-256 re-checked before install;
  - the index-time key allowlist with typed, bounded values;
  - a Splunk client that asserts app names, the packages path and `pw_` targets before every deploy-token call.
- **Agents:** the LLM client (strict JSON schema, 8k output cap for reasoning, token ceiling, bad-output retry cap of 2, logs passed as delimited data), the Profiler and the Index-time agent.
- **Validator:** event count, timestamp accuracy against the truth manifest, and splunkd parser warnings, which fail closed. Two synthetic JSON fixtures with truth manifests, one with offsets and one in Tokyo time without.

**Test results**
- `pytest`: 149 passed, all with fake Splunk and fake model clients. pre-commit and bandit clean.
- `appsec` review: no Critical or High. All 3 Medium and 5 Low findings were fixed, each with an adversarial test:
  - raw splunkd lines no longer reach the model, only fixed summaries;
  - `--tz` is validated as an IANA zone and passed as delimited data;
  - the warning check waits for `_internal` to catch up and also reads `/services/messages`;
  - regexes are timed over the samples and stress inputs to catch catastrophic backtracking (T2.10, brought forward from Phase 4);
  - one-liners: replies with no usage still count against the token ceiling; tag escaping is case-insensitive; control characters are escaped in previews; `::` is refused in sourcetypes; `.env` is read from the repo root.
- After the fixes, the lab run passed again on attempt 1: 60/60 events, 12,907 tokens.
- **Lab, `acme_vpn.json`:** `index-time: PASS (event count 60/60, attempt 1)`, with every `_time` exact and 0 parser warnings, in 30 s and 13,957 tokens. During the run, Splunk showed only the `__test_` app, and the real sourcetype name had 0 events.
- **Lab, `acme_vpn_notz.json`:** attempt 1 set `TZ = UTC` and failed with "60/60 events wrong; most common offset +32400 s". Attempt 2 set `TZ = Asia/Tokyo` and passed 60/60, using 18,988 tokens.

**Cut or deferred**
- Agent `run_search` (code-owned base search, T1.2) moved to Phase 3. Phase 2 agents use Validator evidence only.
- Profile review is auto-approved only; the human review comes with the UI. State is in memory; PostgreSQL comes in Phase 5.
- No "timestamp fallback" check (`_indextime` vs `_time`): the manifest-based accuracy check covers it for synthetic data.
- Infra errors are not retried with backoff yet; an unrecoverable Splunk error ends the run.

**RECORD THIS**
- **First agent fix loop:** `demo/01_fix_loop.sh`, about 1 minute and ~20k tokens. TZ = UTC is caught as +32400 s; attempt 2 sets Asia/Tokyo and passes.
