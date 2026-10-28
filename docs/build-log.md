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

## 2026-10-28 — Phase 3: Extraction and CIM mapper stages, full Validator, generator

**Built**
- **Pipeline:** `parsewright run` now runs three stages: index-time, extraction and CIM mapping.
  - Search-time stages reuse the events indexed by the passing index-time attempt and only reinstall the add-on.
  - Earlier stages' checks re-run after every pass, and the run may backtrack once.
  - Agents learn from the first 200 lines; the Validator checks all 300 events (holdout).
- **Agents:**
  - Extraction (`KV_MODE`, `EXTRACT-` regexes, `DELIMS`/`FIELDS` transforms) and the CIM mapper (`FIELDALIAS`, `EVAL`, eventtypes).
  - Code anchors every eventtype on the attempt's sourcetype and picks the tags from the CIM spec.
  - `test_regex` runs inside the gate; `run_search` with a code-owned base search is built and tested but not yet given to agents (forced tool calls returned 400 in Phase 1).
- **CIM spec:** pinned from the lab's Splunk_SA_CIM **8.7.0** data model definitions (`cim_spec/pin.py`). Splunk's docs site refuses automated fetches. Required fields are the root datasets' `recommended` fields.
- **Validator:**
  - index-time timestamp fallback;
  - extraction coverage, values against the manifest, greedy-regex and duplicate checks;
  - CIM model membership, required fields, allowed values and child datasets, with the three-number score.
- **Generator:** deterministic Acme fixtures in four formats with per-event truth (epoch, category, raw fields, CIM values):
  - JSON with ISO offsets;
  - key=value with epoch milliseconds;
  - syslog with no year and no timezone;
  - CSV with no header row.

**Test results**
- `pytest`: 222 passed, with no live Splunk. That includes the Phase 3 acceptance cases: +10800 s offset evidence, timestamp fallback, greedy regex, duplicates, missing required CIM field, out-of-set `action`, field not in source, search guard refusals and 50-row cap, `test_regex` timing out on `(a+)+$`, and determinism.
- **Lab, all four fixtures green through all three stages:**

  | Fixture | Index-time | Extraction | CIM | CIM score | Tokens |
  | --- | --- | --- | --- | --- | --- |
  | JSON (vpn) | attempt 1 | 1 | 3 | Authentication 4/4, Network_Traffic 7/7 | 117k |
  | key=value, epoch ms (fw) | 1 | 1 | 1 | Network_Traffic 9/9 | 48k |
  | syslog, no year/TZ (ssh) | 1 | 2 | 3 | Authentication 5/5 | 70k |
  | CSV, no header (proxy) | 2 | 3 | 2 | Web 9/9 | 103k |

- **Bugs found in the lab and fixed:**
  - Data model rows were read with an `index=` filter, but `| datamodel` output has no `index` field, so every event was dropped.
  - CIM replies were cut off at the 8k output cap; search-time agents now get 24k.
  - The extraction check expected Splunk's built-in `host`.
  - Ingest did not set a host, so the lab's IP reached evidence and a prompt; ingest now always uses `host=parsewright-sample`.
- `appsec` review: one High and two Medium, plus five Low, all fixed with adversarial tests (threat model, review history).

**Cut or deferred**
- Agents do not call `run_search` themselves yet; prepared context covers the design's context table.
- The CSV fixture has no header row, keeping `INDEXED_EXTRACTIONS` out of scope (Q4).
- Multi-line events (stretch) were not attempted.

**RECORD THIS**
- **First green CIM check:** `demo/02_cim_green.sh [vpn|fw|ssh|proxy]`, a few minutes and 50–120k tokens per fixture. It ends with "holdout: learned from 200 lines, passed on the full file (300 events)" and the CIM numbers.

## 2026-10-28 — Phase 4: Guardrails, adversarial suite, test identity, workflow integrity

**Built**
- **Final gate** (`guardrails/conf_gate.py`), run on exactly what is written before every build, test and promoted alike:
  - allowlisted conf files and keys, compared after NFKC normalisation and case-folding;
  - index-time values re-typed and bounded;
  - `REPORT-` only to the job's own transforms;
  - transform keys limited to `DELIMS`/`FIELDS`;
  - every alias target checked;
  - the whole eventtype search anchored;
  - tags only from the CIM spec;
  - no `[default]` or other non-sourcetype stanza.
- **Validator integrity:**
  - CIM values must trace to a field Splunk extracted (or an approved constant: app, vendor_product, dvc);
  - EVALs may not read anything that differs between test and production (`index`, `sourcetype`, `host`, `now()`, `_indextime`, `random()`);
  - the constant-value check catches gaming that passes the gate;
  - the literal-regex flag is advisory.
- **Approval and promotion:**
  - a passing run records its test package's SHA-256 and waits for `parsewright approve <job> --sha256 …`, which is one-way, so a replay is a no-op;
  - `parsewright promote` hashes and renames the same bytes, refuses an existing TA or sourcetype, installs with `update=false`, records both hashes linked and runs a smoke test;
  - packages are reproducible.
- **Workflow:** per-job and daily ingest caps that fail closed, a private runs folder, no-follow atomic writes, the transform collision check over REST.
- **Tests and demo:** the adversarial suite in `engine/tests/adversarial/`, and a Must-row → test table in the threat model.

**Test results**
- `pytest`: 310 passed. pre-commit and bandit clean; gitleaks over full history clean.
- **Lab, `demo/03_guardrail_block.sh`** on the prompt-injection fixture:
  - the real model ignored the injected instruction, and index-time and extraction passed on attempt 1;
  - a simulated compromised model's proposal (constant `action` plus an anchor-escaping filter) was blocked by the gate and never deployed;
  - a subtler constant passed the gate and was caught by the Validator ("action is always 'success' but the source has 2 values", 181 vs 117 successful logins);
  - the real model then passed: Authentication 4/4, Network_Traffic 7/7.
- **Lab, promotion:**
  - `acme_fw.log` and `acme_proxy.csv`: run, then approve (a wrong hash refused, the replay a no-op), then promote. Both smoke tests passed 20/20, with both hashes linked in the record.
  - A second firewall job was refused at promotion because the TA already exists.
- `appsec` reviewed Phase 4 twice:
  - first pass: one High, two Medium and five Low;
  - second, main review: two High (`[default]` via the sourcetype; EVALs detecting the test environment) and five Medium.
  - All are fixed with adversarial tests; none is open.

**Cut or deferred**
- Run state is in run records, not PostgreSQL, until Phase 5. A same-user forgery is residual risk R9.
- Resume-hash comparison, upload intake checks and rollback on reject arrive with the job queue in Phase 5; escaped log rendering arrives with the UI in Phase 6; routing guardrails in Phase 9.
- The 10-tool-call cap has nothing to count until agents make tool calls.

**RECORD THIS**
- **Guardrail blocking an attack:** `demo/03_guardrail_block.sh`, a few minutes and ~70k tokens.
