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

## 2026-10-28 — Phase 5: Job queue, workers, PostgreSQL ledger, FastAPI, live event stream

**Built**
- **PostgreSQL** (`ledger/`):
  - jobs and an append-only ledger: triggers refuse `UPDATE`/`DELETE`/`TRUNCATE`, and each insert sends a `NOTIFY`;
  - a daily usage table and the kill switch;
  - plain SQL migrations;
  - the engine connects as the limited `parsewright_app` role (`SELECT`/`INSERT` on the ledger only); the owner account is used only by `parsewright migrate`.
- **Queue and workers:**
  - claims with `FOR UPDATE SKIP LOCKED`, a 2-minute lease and heartbeats;
  - checkpoints after the profile, every attempt and every passed stage, so a crashed job resumes on another worker and never reuses a sourcetype;
  - a job waiting for profile review is released;
  - a cluster-wide advisory lock for Splunk writes, two LLM slots, the daily token budget and the kill switch;
  - approved jobs are promoted by a worker;
  - `parsewright serve` runs the API with a worker pool that restarts dead workers, and workers exit if `serve` dies.
- **API** (FastAPI):
  - upload checks: bounded `.gz`, no archives, binary or non-UTF-8, at least 50 events, at most 10,000-character lines, a validated manifest, and a token estimate capped at the run ceiling;
  - duplicate detection;
  - runs, profile confirm, approve/reject, `.tgz` download, and an SSE stream from `LISTEN/NOTIFY`;
  - CSRF header and Origin check, CORS, TrustedHost, security headers, body-size cap and a cap on streams.
- **CLI, Docker and CI:**
  - the CLI shares the queue (`run`, `status`, `approve`, `promote`, `worker`, `serve`, `kill`, `migrate`), and `run --local` keeps the database-free mode;
  - `engine/Dockerfile` (non-root); compose `migrate` and `engine` services with `cap_drop: ALL` and a read-only root filesystem;
  - a PostgreSQL service container in CI.

**Test results**
- `pytest`: 354 passed, 32 of them against real PostgreSQL. They cover:
  - 20 jobs on 4 workers, never claimed twice;
  - crash and resume from the checkpoint, with the crashed worker fenced off;
  - the ledger refusing `UPDATE`/`DELETE`/`TRUNCATE`, and the app role refused even `DISABLE TRIGGER`;
  - the upload refusals (bomb, multi-member `.gz`, tar, tar.gz, zip, binary, Latin-1, too few events, symlinks);
  - duplicates pointing to the existing job;
  - approve refused unless `awaiting_approval`;
  - the event stream delivering a transition within 2 s;
  - CSRF.
- pre-commit, bandit and pip-audit clean.
- **Lab, `demo/04_parallel_jobs.sh`:**
  - four fixtures were uploaded at once and four workers ran them in parallel;
  - the SSH job paused for profile review while the other three continued, then resumed on confirm and recovered from a CIM failure with one backtrack;
  - all four reached `awaiting_approval` in about 5 minutes (332k tokens in total).
- **Lab, approve and promote through the API:** a wrong hash refused (409), the replay a no-op; a worker promoted `TA-parsewright-acme-fwdemo` (smoke 20/20); the download served the promoted `.tgz`; the ledger shows one claim to build and one to promote.
- **Lab, after the fixes:** a cross-site upload was refused (403) and the same-origin upload was detected as a duplicate. Killing `serve` with SIGKILL left no orphaned workers.
- `appsec`: one High (CSRF) and six Medium, plus ten Low; all fixed with tests except the hashed dependency lock (T9.6, Phase 10).

**Cut or deferred**
- Uploads need the generator's truth manifest; manifest-free validation of real logs is planned.
- Correct-a-mapping in review: only approve and reject.
- Docker: `docker compose up` (engine, Splunk, PostgreSQL, `/health`) is written but not yet run, because this session cannot use Docker. The compose Splunk also needs the Phase 10 bootstrap (tokens, `pw_test`, CIM macros) before the engine can use it.
- No login: the API is localhost-only (R1), and the compose network can reach it (R10).

**RECORD THIS**
- **Parallel jobs:** `demo/04_parallel_jobs.sh` with `parsewright serve --workers 4` running, several minutes and ~330k tokens.

## 2026-10-28 — Phase 6: Next.js UI (four screens)

**Built**
- **Screens** (Next.js 16, React 19, Tailwind, shadcn-style components):
  - the job board with upload, refreshed every 3 s;
  - the live run view: a stepper and the ledger timeline over SSE (`EventSource`, capped at 500 rows);
  - profile review: vendor, product, sourcetype and time zone, editable before the run continues;
  - the approval report: CIM scores, raw events beside parsed fields with highlights, the mapping table, the exact `.conf` files, the holdout counts, download, and approve/reject behind a second confirmation that names the package hash.
- **Report data from the engine** (`orchestrator/report.py`): saved when a run passes. Raw and parsed values come from the same search row; highlight offsets are computed in the engine, non-overlapping and in UTF-16 (what the browser counts), so the UI only turns `(start, end, field)` into `<mark>` elements.
- **Safety:**
  - the browser talks only to the Next.js server. `/api/engine/*` forwards an allowlist of engine paths, refuses encoded separators and dot segments, requires the CSRF header and an allowed Origin for actions, follows no redirects, and forwards only a few headers;
  - `proxy.ts` refuses unknown `Host` headers (DNS rebinding) and sets a per-request CSP nonce with `strict-dynamic`, so no `'unsafe-inline'` scripts;
  - log text is rendered only as React text. ESLint fails on `dangerouslySetInnerHTML`, `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`, `srcDoc`, `eval` and `new Function`.
- **Packaging:** `web/Dockerfile` (standalone output, non-root, multi-stage); the compose `web` service with `cap_drop: ALL` and a read-only root filesystem; CI installs Node 24 and Playwright's Chromium; `make setup`, `lint`, `test` and `security` cover `web/`.

**Test results**
- Playwright, 8 passed, against the standalone `server.js` the Dockerfile runs:
  - XSS: a `<script>` and `<img onerror>` payload in log text, field values, the timeline, the `.conf` view, the board and profile review renders as text, with no dialog and no injected element;
  - the keyboard-only flow (upload, confirm the profile, approve with its second confirmation) in tab order;
  - the live view showing a ledger event within 2 s;
  - the proxy: an unknown Host refused (421) on pages and the API, cross-site and header-less actions refused (403) with a positive control, encoded and dot-segment paths refused, security headers and a fresh nonce on every page.
- `pytest`: 357 passed (3 new for the report: highlights, UTF-16 offsets, raw and fields from one row).
- ESLint, `tsc --strict` and pre-commit clean; `npm audit`: 0 vulnerabilities.
- **Lab, `demo/05_approval_report.sh`:** the injected VPN fixture (its last event ends with `<script>alert(document.cookie)</script>`) ran to `awaiting_approval` with a full report: 15 events with highlights, 8 mapping rows, Authentication 4/4 and Network_Traffic 7/7. In the browser the script line shows as text. Live checks: a rebinding `Host` got 421, a header-less POST through the proxy got 403, and the CSP carried a nonce.
- `appsec`: one High (DNS rebinding, T8.5) and one Medium (`'unsafe-inline'` scripts), plus Lows; all fixed with tests.

**Also found and fixed**
- A Phase 5 test reset the `parsewright_app` password. PostgreSQL roles are server-wide, so this broke the running engine (500s). The test now uses `SET ROLE` and touches no password; the role was restored with `parsewright migrate`.
- Next.js 16.4.0 had critical advisories, so it is pinned to the patched 16.4.3: a deliberate exception to the two-week version rule.
- The e2e server first ran `next start`, which Next does not support with `output: "standalone"`. It now runs `server.js`, as Docker does.

**Cut or deferred**
- Correct-a-mapping in review: only approve and reject (as in Phase 5).
- The board polls every 3 s rather than using a jobs stream.
- No login: the UI is localhost-only, protected by the Host and Origin allowlists.
- The web container has not been built here (this session cannot use Docker); it is part of the Phase 10 `docker compose up` check.
- Node 24.22.0 was installed under `~/.local/node` on the build host (checksum verified); the browser tests needed Chromium's system libraries and fonts.

**RECORD THIS**
- **Approval report with an injected log line shown as text:** `demo/05_approval_report.sh` with `parsewright serve` and the web UI running, then open the printed `http://localhost:3000/runs/<job>` URL. Show the raw-versus-parsed highlights, the CIM scores, then the approve confirmation naming the hash.

## 2026-10-28 — Phase 7: Parser updates

**Built**
- **TA registry** (migrations 003–004): every promoted TA with its versions (append-only), the job that built each one (its samples, manifest and profile are the regression set), and a history of registrations, updates and rollbacks. TAs promoted through the database before the registry existed were backfilled.
- **Update job** (`parsewright update <TA> <file>`, or "Update an existing TA" on the upload form), Diagnose → failing stages only → Regression → Approval → Promote:
  - Diagnose installs the production TA from its hash-checked package under the job's test identity and runs every check on the new samples and on every registered version's samples, which share one test sourcetype told apart by `source`. No model call; if everything passes, the job ends there with 0 tokens;
  - patch mode: only failing stages run, a later stage that passes as it is is skipped, and the agent gets the production settings, the drift evidence and old-format events with an instruction to make the smallest change;
  - every attempt is checked on old and new samples, so a patch that fixes v2 but breaks v1 is rejected with that evidence; a patch may add eventtypes but never drop or rename a production one;
  - review: diff against production, `local/` override flags, index-time vs search-time notes, an old event parsed by the update and the rollback command; the version goes up one minor step above the highest registered version.
- **In-place promotion and rollback:** `update=true` only over a registry TA at the expected installed version with the Parsewright marker, under one lock per TA; `local/` is kept (lab Q11); after the install, the effective settings are read back and a changed key that is not in effect fails the smoke test. `parsewright rollback <TA> <version>` rebuilds the exact version from its kept package (the hash must match before and after).
- **Validator:** a new index-time check that `TIME_FORMAT` really matches every event. `TIME_FORMAT` may now be left out only with `TIME_PREFIX` and `MAX_TIMESTAMP_LOOKAHEAD` set: that is how two formats coexist in one sourcetype.

**Test results**
- `pytest`: 403 passed (46 new), including against real PostgreSQL. The tests cover:
  - 0 tokens when the new samples pass as they are;
  - the old-format rejection carrying evidence to the next attempt;
  - only the failing stage's agent running;
  - test identity there and back through the real final gate;
  - kept packages with `..`, links, other apps, `bin/` or `local/` refused;
  - nothing in the engine writing `local/` or `configs/conf-*`;
  - in-place update refused for a missing, other-version or non-Parsewright app;
  - exact rollback, and a tampered package refused;
  - registry versions append-only, with compare-and-set on the current version;
  - the registry lock, and the app role limited to `current_version`;
  - the `TIME_FORMAT` check, including a backtracking bomb and a format that works only because Splunk guesses.
- Playwright: 9 passed. New: the update review (diff, overrides, old event) renders log-derived text as text; the keyboard flow includes the new TA selector. ESLint, `tsc` and pre-commit clean.
- **Lab, `scripts/probe.sh update` (lab-findings Q11):** `update=true` keeps `local/` and a `local/` value still overrides the new default; a changed `TIME_FORMAT` on an existing sourcetype applies with no reload; `[default]` is not readable over REST.
- **Lab, firmware v2 against `TA-parsewright-acme-fwdemo` 1.0.0** (job `866b4273`, 37k tokens):
  - Diagnose with no AI: index-time failed (the v1 `TIME_FORMAT = %s%3N` cannot match ISO 8601: all 300 v2 timestamps were only guessed) and CIM failed (`src` unmapped);
  - the index-time patch dropped `TIME_FORMAT`, kept the pin and passed on v1 and v2; extraction passed as it was and was not patched;
  - CIM attempt 1 (`FIELDALIAS src_ip AS src`) fixed v2 but broke v1 and was rejected with that evidence; attempt 2 (`EVAL-src = coalesce(src_ip,src)`) passed both;
  - regression passed on both, with Network_Traffic 9/9; awaiting approval as 1.0.0 → 1.1.0, with a diff that touches only `props.conf` and `app.conf`.
- **Found in the lab and fixed:**
  - the first lab run showed that a wrong `TIME_FORMAT` passed every existing check, because Splunk silently guessed the timestamps correctly; that is the new `TIME_FORMAT` check;
  - the same run showed patch mode letting the agent rename the production eventtype; agents now see the plain names and the gate refuses a dropped eventtype. Both earlier lab jobs were rejected.
- `appsec`: one High (the new check could backtrack for hours), two Medium (regression samples read from any path; promotion and rollback not serialised) and six Low; all fixed with tests except L5 (accepted, see the threat model).

**Cut or deferred**
- Overrides are checked for props only, not `transforms.conf` or `eventtypes.conf`.
- Rollback is CLI only, with no UI button.
- The two TAs promoted in Phase 4 file mode are not in the registry, so only TAs promoted through the database can be updated.

**Lab, Oct 30 (owner approval):**
- The owner approved `866b4273` in the UI. Four seconds later a worker updated `TA-parsewright-acme-fwdemo` in place, 1.0.0 → 1.1.0, rebuilt from the approved package `d05bc005…` (installed as `f4bc33f9…`). Smoke test 20/20 passed, and the read-back found every changed setting in effect. Registry: current 1.1.0, versions 1.0.0 and 1.1.0.
- `demo/06_parser_update.sh diagnose` (job `1a0521ec`): a fresh batch of 120 v2 events ended at Diagnose, "no change needed", **0 tokens**.
- `parsewright rollback TA-parsewright-acme-fwdemo 1.0.0` (owner's go-ahead): the installed TA went back to 1.0.0, package `1b8f5119…`, rebuilt to the registered hash. The effective settings are v1 again (`TIME_FORMAT = %s%3N`, lookahead 20, no `EVAL-src`). The registry is current 1.0.0, with 1.1.0 kept and a `rolled_back` event recorded. No package was left behind. The next update of this TA will be 1.2.0.

**RECORD THIS**
- **Parser update:** with `parsewright serve` and the web UI running, run `demo/06_parser_update.sh`, then open the printed job page: Diagnose, the patch rejected for breaking v1, both formats passing, and the diff. Approve in the UI (a worker updates the TA in place to 1.1.0), then run `demo/06_parser_update.sh diagnose`: a new v2 batch ends at Diagnose with 0 tokens. Undo with `.venv/bin/parsewright rollback TA-parsewright-acme-fwdemo 1.0.0`.

## 2026-10-30 — Phase 7b: UI redesign (agent-centred, readable, navigable)

**Built**
- **Event labels (engine, data only):** every ledger log event carries `stage`, `attempt`, `visit`, `actor`, `kind` and a structured `detail` (proposed settings, check results with expected vs actual, evidence, the parser-update review's `changes` rows). The text line the CLI prints is unchanged; each Validator report is now one event instead of one per line.
- **Actor identity system** (`web/lib/actors.ts`): ten actors, each with one icon, accent, tagline and kind marker. AI agents are round with a sparkle, code is a rounded square with a gear, Splunk is a double-ringed square marked SPL, and you are a dashed circle with a hand. Light and dark tokens, with every text and status pair checked for WCAG AA.
- **Screens:**
  - runs board: "Needs you" pinned, the phase, the agent at work and attempt x/5 per job, "New run" as a side sheet;
  - run workspace: budget meters, a "Now" banner, and a phase rail you can click, deep-link (`?phase=&attempt=`) and move along with arrow keys. Each attempt shows its proposal, the gate's verdict, the Splunk checks with up to 3 failing events, the outcome and the diff from the previous attempt. Backtracks are said in words;
  - live activity: grouped by phase and attempt, with filters and "Jump to latest";
  - config and diffs as rows with plain labels; raw vs parsed with one colour per field and a CIM view;
  - approval summary and a sticky decision bar; profile review with coverage bars and "you changed this"; a read-only TA registry.
- Parser-update Diagnose is shown as Validator and Orchestrator work (no AI); update jobs have their own rail (Diagnose → patched stages → Regression → Approval → Promoted).

**Test results**
- pytest: 418 passed (15 new for the event labels).
- Playwright: 12 passed. New tests:
  - no diff view shows `---`, `+++`, `@@` or a leading `+`/`-`;
  - deep links with back and forward;
  - arrow keys on the phase rail;
  - XSS through the activity feed, the phase view (failing examples, evidence, rationale), the config view, the board's "Needs you" and the update's row diff;
  - the keyboard flow now opens the new-run sheet, and the confirm dialog focuses Cancel.
- ESLint, `tsc`, pre-commit, bandit and pip-audit clean.
- `npm audit` fails on a moderate `minimatch` advisory in ESLint's dev dependencies. It was published after Phase 7; the only fixed release (11.0.1, Oct 27) is a major version and younger than the two-week pinning rule. It was left for the owner.
- semgrep and gitleaks are not installed on the build host; gitleaks ran in pre-commit and the full `make security` runs in CI.
- `appsec`: no High or Medium findings. Fixed:
  - L1: board polling could stack up; it is now one round at a time, idle in a hidden tab, with a bounded history;
  - L2: Approve is now offered only with a valid SHA-256;
  - prototype-free lookup tables;
  - stable keys for the override warnings;
  - the confirmation focuses Cancel.

**Cut or deferred**
- No new UI package: dialogs and the sheet use the native `<dialog>` instead of the planned Radix Dialog.
- The Profiler has no confidence field, so profile review shows coverage only.
- The 15-minute meter measures from the latest run start (a resumed job gets a fresh 15 minutes, as the worker does).
- Mapping corrections in the UI remain out of scope.

**RECORD THIS**
- **The live workspace:** with `parsewright serve` and the web UI running, run `demo/07_live_workspace.sh`, confirm the profile on the printed page, then watch the Now banner and the phase rail, and open an attempt's diff and checks.

**Follow-up, Oct 31 (owner review of the first version)**
- **Dark glass theme** replaces the light and dark pair. It has translucent panels over soft colour glows, a gradient primary button and glowing agent avatars. Every text and status pair was re-checked for WCAG AA against the lightest panel.
- **Configuration as the .conf file:** an editor-style pane with a title bar, line numbers, syntax colours and a read-only status line. "Explain settings" adds a plain-language note under each known key.
- **One raw vs parsed view:** a parser update's old-format event moved into it behind a "New format / Old format" switch. Before, it was a second, near-identical block.
- **Older runs:**
  - runs recorded before the event labels showed every line as Orchestrator and their phases as not started. `web/lib/legacy.ts` reads those text lines once, in order (display only), so they show the agents, attempts, proposals as settings and merged check reports;
  - a run past approval never shows an earlier phase as not started;
  - an update recorded before structured `changes` shows its stored diff as rows, without markers.
- Playwright: 14 passed. New tests: an unlabelled older run, and an older update's diff.

## 2026-10-31 — Phase 10: Docker setup for judges, README, demo preparation (in progress)

**Built**
- **One command (`make up`, `scripts/up.sh`):**
  - `.env` is created from the template, and every placeholder password is replaced with a random one;
  - Splunk and PostgreSQL start and become healthy;
  - Splunk is then prepared from inside its own container (`scripts/splunk_bootstrap.py`, port 8089 stays unpublished): the `pw_test` index, the three no-inheritance roles and users from lab-findings Q9, the CIM add-on installed from `lab/` with its index macros set to `(index=pw_*)`, and one fresh 7-day token per account. The tokens are written into `.env` by `scripts/env_set.py` and never printed;
  - the engine and the UI start, and the engine becomes healthy.
- **`make first-run`:** uploads the bundled synthetic VPN log and follows it to the approval report, using only the standard library.
- **Docs:**
  - the README quick start rewritten for judges (Docker, `make` and Python 3 only); every stale "planned" label corrected; a screenshot from synthetic data;
  - `docs/demo-script.md`, a timed 3-minute script built from the `demo/` scripts;
  - the hackathon checklist ticked where verifiable.
- **CI unblocked:** `npm audit` now covers the packages the UI ships (`--omit=dev`): 0 vulnerabilities. The ESLint `minimatch` advisory is residual risk R11, to be revisited on Nov 10.

**Test results**
- pytest: 427 passed (9 new for the two scripts that write `.env`, including refusals of every key other than the three tokens and of quoting or shell characters).
- Playwright: 14 passed. pre-commit, bandit and pip-audit clean.
- `appsec` final sweep: gitleaks over the full history (46 commits) clean, no internal names or private IPs, every port bound to 127.0.0.1. No High findings. Fixed:
  - two Medium: a JWT-shaped literal in a test, and a 90-day token life;
  - four Low.

**Not verified yet**
- The stack has not been run here: this host's user cannot reach Docker. The clean-VM test (`make env`, set `LLM_API_KEY`, CIM package in `lab/`, `make up`, `make first-run`, timed) is the owner's step, as planned.
- Image digests and the CIM package checksum are not pinned (residual risk R12): the digests could not be fetched from this host.
