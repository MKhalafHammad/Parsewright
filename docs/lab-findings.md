# Lab findings (Phase 1)

> Every open question from [design.md](design.md), plus those the build plan added. Each has how to test it, the result and the decision it causes. **Expectation** lines are unverified hypotheses written before testing; only **Result** lines count. Never paste tokens, passwords, real hostnames or IPs here.

## Summary

| Q | Question | Answered by | Status | Decision |
| --- | --- | --- | --- | --- |
| Q1 | Does the Meta Model API support `response_format` JSON schemas, or do we need a forced tool call? | `probe_llm` | Answered 2026-10-27 | `response_format` with a strict JSON schema |
| Q2 | What is "contributor mode"? | Meta docs | Answered 2026-10-27 | Standard mode; contributor variant only for synthetic-only dev runs, if ever |
| Q3 | Do index-time settings apply to the next ingest right after a reload? | `probe_install`, `probe_update` | Answered 2026-10-27 (new sourcetype), 2026-10-28 (changed settings, same sourcetype) | Applied right after install, no reload or restart needed, in both cases |
| Q4 | Which edge cases are in scope? | Decision | Decided 2026-10-27 | In: multiple event types, missing TZ, epoch. Stretch: multi-line. Out: CSV `INDEXED_EXTRACTIONS` |
| Q5 | Four agents, or merge Extraction and CIM mapper into three? | Decision | Decided 2026-10-27 | Four agents |
| Q6 | Deploy path: install a package, or write stanzas over REST? | `probe_install` + decision | Answered 2026-10-27 | A: package install via `apps/local`; `update=true` is a full replace |
| Q7 | How to run `btool check` without shell access to Splunk | Decision | Decided 2026-10-27 | Option 1: allowlist + typed values before deploy, fail on any splunkd warning after install |
| Q8 | Ingest path: does `receivers/simple` apply line breaking and timestamps? | `probe_splunk` + `probe_install` | Answered 2026-10-27 | `receivers/simple` |
| Q9 | Which capabilities does the deploy role need? | `probe_splunk` + `probe_install` | Answered 2026-10-27 | `admin_all_objects`, `edit_tcp`, `install_apps`; one shared test index, no `indexes_edit` |
| Q10 | CIM add-on installed, `pw_*` in the CIM index macros | Manual lab step + search-token check | Done 2026-10-27 | Lab prerequisite met |
| Q11 | Does an in-place update (`update=true`) keep an admin's `local/`, and can the review see overrides? | `probe_update` | Answered 2026-10-28 | Yes: promote updates in place; flag overrides from the effective settings, with system defaults in code |

## Lab setup (OWNER ACTION, once)

1. **Start Splunk:** the lab VM, or `make up` for the Docker stack. Log in to Splunk Web as `admin`.
2. **Create the test index:** in Settings → Indexes, create `pw_probe`.
3. **Create three roles** (Settings → Roles):
   - **`parsewright_search`**
     - Inherits nothing. Inherited index access cannot be removed in a child role, so inheriting `user` could widen what it can search.
     - Capability: `search`.
     - Indexes searched by default and allowed: only `pw_*` and `_internal`.
     - Remove access to every other index.
   - **`parsewright_deploy`**
     - Inherits nothing.
     - Start with the capabilities in Q9's expectation and trim them after the probe.
     - Allowed indexes: `pw_*`. This limits only what the role can search. Splunk does not limit which index a role can **write** to; see Q9.
   - **`parsewright_drift`**
     - Inherits nothing.
     - Capability: `search` (read-only).
     - Search filter set later (Phase 8).
4. **Create three users** (Settings → Users), one per role, each with a long random password you don't keep. Tokens are how they authenticate. Remove the pre-selected `user` role, so each user has only its own role.
5. **Create the tokens:** Settings → Tokens → enable token authentication, then create one token per user. Paste them into `.env` as `SPLUNK_SEARCH_TOKEN`, `SPLUNK_DEPLOY_TOKEN` and `SPLUNK_DRIFT_TOKEN`.
6. **Point `.env` at Splunk:** set `SPLUNK_HOST` and `SPLUNK_PORT` to the lab's REST address.

## Running the probes (OWNER ACTION)

```bash
scripts/probe.sh llm              # loads .env into the probe's process only
scripts/probe.sh splunk
```

Against the Docker stack, port 8089 is not published to your machine (by design). Run the Splunk probe inside the Compose network instead:

```bash
docker run --rm --network parsewright_default \
  -e SPLUNK_HOST=splunk -e SPLUNK_PORT -e SPLUNK_SEARCH_TOKEN -e SPLUNK_DEPLOY_TOKEN \
  -e PYTHONPATH=/engine -v "$PWD/engine:/engine:ro" python:3.12-slim \
  sh -c "pip install -q splunk-sdk==2.1.1 && python -m parsewright.tools.probes.probe_splunk"
```

This passes only the two tokens the probe needs (exported by the `set -a` line above), never the whole `.env` with the admin and database passwords. It also mounts the source read-only.

Both probes print only usernames, roles, capability names, counts and pass/fail lines; they never print tokens or prompts. Paste their output under **Result** below. **Remove any hostname or IP first**: error messages can name the lab VM.

## Q1. Structured output from the Meta Model API

- **Why it matters:** every agent returns a schema-validated object. The LLM client (Phase 2) needs to know which mechanism to use.
- **How:** run `probe_llm`. It sends one tiny request with `response_format: json_schema` and, if that fails, one with a forced tool call. It prints which mode works and the token count.
- **Expectation:** at least one mode works. If neither does, Phase 2 falls back to JSON in plain text, validated by Pydantic, with the "bad output" retry cap of 2.
- **Result (2026-10-27):**
  - **First run, with `max_tokens=50`:** `response_format` returned output that failed validation, and the forced tool call was refused with HTTP 400. The probe then printed only error class names, so the cause wasn't visible.
  - **Second run:** the probe now allows 512 output tokens, prints safe failure details, and also tries `tool_choice="required"` and `json_object`. Output:
    ```
    response_format: PASS (tokens in=27 out=316)
    structured output mode: response_format
    ```
  - **Cause of the first failure:** a one-word answer used 316 output tokens, so the model reasons before answering and the 50-token cap cut the JSON off.
  - The forced-tool 400 was not re-tested, because the probe stops at the first mode that passes.
- **Decision:**
  - **Mode:** every agent uses `response_format` with `json_schema` and `strict: true`, and its Pydantic model's schema. Pydantic still validates every reply, and the "bad output" retry cap of 2 still applies.
  - **Output cap:** the LLM client never sets a small `max_tokens`. Each agent's cap leaves several hundred tokens for reasoning on top of the expected output. Hitting the cap (`finish_reason=length`) counts as bad output, not a stage failure.
  - **Budget:** reasoning tokens are billed as output. Per-run token ceilings and cost estimates use measured `completion_tokens`, not the size of the JSON.
  - **Fallback:** forced tool calls are not pursued unless `response_format` regresses.

## Q2. "Contributor mode"

- **Why it matters:** design.md says to default to standard mode until this is confirmed.
- **How:** read the Meta Model API docs or the hackathon guide (OWNER, since it needs your account).
- **Result (2026-10-27, from Meta's docs, read by the owner):**
  - In contributor mode, Meta may use the content sent and received (prompts, files, context and model responses) to train future Meta models. In exchange, usage is discounted.
  - On the Meta Model API it is not a setting: you call a model's **contributor-mode variant** instead of the standard model. The variant's name is on the docs page "How do I use Contributor mode on Meta Model API?", not yet read.
  - It is unavailable to accounts with Zero Data Retention.
  - The terms forbid sending sensitive, confidential or personal information to these discounted services. Use cases with personal information must use standard services.
- **Decision:**
  - **Parsewright uses standard mode.** Its input is customers' logs, which are confidential by nature, and the design's on-prem mode exists so logs never leave the network.
  - The default `LLM_MODEL` names the standard model.
  - A contributor-mode variant may be set through `LLM_MODEL` **only for runs on synthetic fixtures**, for example to stretch the hackathon credits. Never with real logs.
  - Never in on-prem mode, and never as the default.
  - The README states this when it documents `LLM_MODEL`.

## Q3. Index-time settings after a reload

- **Why it matters:** the inner loop deploys, reloads (no restart) and ingests at once. If index-time settings (`LINE_BREAKER`, `TIME_FORMAT`, `TZ`) only apply after a restart, the loop design changes.
- **How** (manual, about 10 minutes, after Q6 picks a deploy path):
  1. Deploy a test app with `[pw_probe_lb]` containing `SHOULD_LINEMERGE = false` and `LINE_BREAKER = (;)`.
  2. Reload: `| rest /services/configs/conf-props/_reload` or the debug/refresh endpoint.
  3. Ingest `a;b;c` with `sourcetype=pw_probe_lb` into `pw_probe`.
  4. Count. **3 events** means the reload applied index-time settings; **1 event** means it didn't.
  5. Repeat with a `TIME_FORMAT`/`TZ` change and compare `_time`.
- **Expectation:** on a standalone instance a props reload is picked up by new inputs. Needs proof on this Splunk version (10.6.1 in Docker).
- **How it was tested:** `scripts/probe.sh install` (`probe_install`), not the manual steps above. Run against the owner's standalone lab Splunk, not the Docker image.
  1. It installs a test add-on whose sourcetype has `LINE_BREAKER = (;)`, `TIME_PREFIX = ts=`, `TIME_FORMAT = %Y-%m-%d %H:%M:%S` and `TZ = Pacific/Chatham`. The +13:45 zone means a correct `_time` cannot come from the server's own zone.
  2. It posts `a;b;c`, each event with a timestamp, through `receivers/simple` straight after the install, without reloading.
  3. It checks that there are 3 events and that `_time` exactly equals the expected epochs.
  4. Only if that fails does it reload `conf-props` and retry.
- **Result (2026-10-27):**
  ```
  ingest right after install, no reload: 3 events (expect 3: LINE_BREAKER applied), _time matches TIME_FORMAT+TZ
  ```
  Index-time settings from a newly installed add-on apply to the very next ingest. Neither a reload nor a restart was needed, so the reload fallback never ran.
- **Not yet tested:** changing the settings of a sourcetype that already exists, by reinstalling with `update=true` under the same sourcetype name. The probe's v2 used a new sourcetype name.
- **Decision:**
  - The inner loop is install, then ingest, with no restart.
  - Each attempt uses its own sourcetype name, so every attempt is the tested "new sourcetype" case. The attempt number goes into the `__test_<job>` suffix, for example `<st>__test_<job>_a<n>`.
  - Phase 2 keeps one reload call (`configs/conf-props/_reload`) as a safety net, used only if the event count is wrong, and logs when it was needed.

## Q4. Edge cases in scope

The candidates from design.md:
- multiple event types per file;
- multi-line events;
- a missing timezone;
- epoch timestamps;
- CSV headers (`INDEXED_EXTRACTIONS`).

- **Recommendation:**
  - **In scope:** multiple event types per file, missing timezone and epoch timestamps. They are cheap with the generator and demo well; "missing TZ" is the classic +3 h error.
  - **Stretch:** multi-line events.
  - **Defer:** CSV with `INDEXED_EXTRACTIONS`, because it is index-time structured parsing with different rules. Keep CSV via search-time `REPORT-`/`DELIMS` instead.
- **Decision (OWNER, 2026-10-27):** the recommendation above.
  - **In scope:** multiple event types per file, missing timezone and epoch timestamps (seconds and milliseconds).
    - Each gets a generator fixture with a truth manifest.
    - Each gets Validator checks: per-event-type field coverage, and `_time` compared with the manifest's epochs.
    - A missing timezone is flagged by the Profiler for the human to confirm at profile review.
  - **Stretch:** multi-line events, only if Phase 3 finishes early.
  - **Out:** CSV with `INDEXED_EXTRACTIONS`. CSV is still supported through search-time `REPORT-`/`DELIMS`.
  - The README lists the out-of-scope and stretch cases as "planned".

## Q5. Four agents or three

- **Recommendation:** keep four, as the design has them. Separate context and ownership are what make failure routing and "agents never grade themselves" clear. Merging saves one prompt but blurs which agent owns a failing check. Revisit only if Phase 3 runs late.
- **Decision (OWNER, 2026-10-27):** **keep four agents**: Profiler, Index-time, Extraction and CIM mapper.
  - **Accuracy:** each agent's context stays focused, so the CIM mapper never sees regex attempts and Extraction never sees the CIM spec. A failing check routes to exactly one owner.
  - **Safety:** the agent that maps to CIM cannot rewrite extractions to game a CIM check.
  - **Fallback:** merging Extraction and CIM mapper stays the documented fallback only if Phase 3 runs late.

## Q6. Deploy path

The design says to "write the new TA version to `/opt/splunk/etc/apps/TA-*/default/` via REST". There are two ways to do that:

| | A. Package install (`apps/local`, `update=true`) | B. Config endpoints (`configs/conf-props`, `conf-transforms`, … with an app namespace) |
| --- | --- | --- |
| Needs | The `.tgz` readable on the Splunk host: a shared Docker volume, or `scp` to the VM | Only REST |
| Writes | Exactly the tested package (`default/`, `metadata/`, `lookups/`) | Stanzas, usually into the app's `local/`, not `default/` |
| Fits hash-bound approval (T3.5) | Yes, since the installed bytes are the approved `.tgz` | Weaker, since the installed state is rebuilt from calls |
| Fits design ("`local/` never written") | Yes | **No**: conflicts with the parser-update rule that `local/` belongs to admins |

- **Recommendation:** **A, package install.** In Docker, mount a dedicated volume read-only into `splunk` (for example `/opt/parsewright/packages`) and read-write into `engine`. Only `.tgz` files go there. On the VM, use the same path with a copy step.
- **How to verify:**
  1. Install a trivial `TA-parsewright-acme-probe__test_probe.tgz` with `parsewright_deploy`'s token, then confirm it appears in `apps/local`.
  2. Try the same with the search token, which must be refused.
  3. Reinstall with `update=true` from a package whose `default/props.conf` has a different set of stanzas, then confirm the installed app holds exactly the new package's stanzas: a full replace, not a merge.
- **Result (2026-10-27):** `scripts/probe.sh install`, which builds the packages in `PARSEWRIGHT_PACKAGES_DIR` (owned by the engine user, mode 755, readable by `splunk`):
  ```
  install with search token: refused HTTP 403 (good)
  install v1 with deploy token: ok
  v1 stanza present after install: True
  reinstall v2 with update=true: ok
  after v2: v1 stanza present=False, v2 stanza present=True (full replace)
  cleanup: test add-on uninstalled
  install probe: PASS
  ```
  - The search token cannot install apps.
  - The deploy token installs from a path on the Splunk host.
  - `update=true` **replaces** the add-on's config instead of merging it, so a stanza dropped from a later package really disappears. This confirms the "always build the complete package" rule below.
  - The deploy token can also uninstall the test add-on.
- **Decision (OWNER, 2026-10-27):** **A, package install.**
  - Each attempt installs the complete add-on as a `.tgz` through `apps/local` with `update=true`, using the deploy token.
  - All agent-proposed stanzas are written by the escaping conf writer into `default/*.conf` inside the package. Nothing is written over the `configs/conf-*` endpoints, so `local/` is never touched.
  - The TA builder regenerates the full package on every attempt, with the stanzas from every stage so far, never a delta. `update=true` replaces `default/` as a whole, so a partial package would drop earlier stages' stanzas.
  - Packages reach Splunk through a dedicated shared folder, `/opt/parsewright/packages`, mounted read-write in `engine` and read-only in `splunk`, holding only `.tgz` files. On the VM, a copy step puts them at the same path.
  - Follow-ups:
    - Phase 2 adds the shared volume to `docker-compose.yml` for the Docker lab.
    - On a Splunk running directly on the host, `PARSEWRIGHT_PACKAGES_DIR` is a plain directory: `/opt/parsewright/packages`, owned by the engine user, mode 755. Not `/tmp`, where any user could plant a package.

## Q7. `btool check` without shell access

`btool` runs on the Splunk host. The tempting fix is to mount the Docker socket into the engine so it can `docker exec`, but that hands the engine root on the host (threat T7.5), so **it is ruled out**.

- **Options:**
  1. **Local check in the engine:** the escaping writer guarantees syntax. The gate checks keys and values against an allowlist of known settings with valid types. Then the deploy reload's messages are read back through REST (`/services/messages`, splunkd warnings on `_internal`).
  2. **A minimal sidecar in the Splunk container**, exposing only "run `btool check` for app X". It is more moving parts and a new attack surface.
- **Recommendation:** option 1, but only if it **fails closed**: any splunkd warning or error about the test app after reload fails the attempt. The writer plus allowlist cover what `btool check` catches for the keys we allow (unknown keys, bad stanzas), and Splunk's own warnings after reload catch the rest.
- **If chosen:** the same PR must update design.md (the "`btool check` before deploy" Must row) and threat T2.11's control text.
- **Decision (OWNER, 2026-10-27):** **option 1.**
  - **Before deploy:** the escaping writer makes malformed stanzas impossible. The gate checks every key against an allowlist with typed values and bounds, so unknown, misspelled or out-of-scope keys are rejected before Splunk sees them.
  - **After install and ingest:** a fixed Validator search over `_internal` (`log_level IN (WARN, ERROR)`, `component` from the parsing pipeline, mentioning the attempt's sourcetype or app, during the ingest window) plus `/services/messages`. Any hit fails the attempt; so does an error or timeout of the check itself (fail closed). The message is passed to the owning agent as evidence.
  - **Limit (appsec review):** splunkd does not warn at runtime about unknown or misspelled props keys; only btool does. So the allowlist is the **only** syntax control, and must reject every key not on it. The post-install check catches parsing problems such as timestamp and line-breaking warnings.
  - **Transform collisions:** the transform-name collision check, which the design also did with btool, becomes a REST read of existing transform names (`configs/conf-transforms`) before deploy.
  - **Ruled out:** a sidecar and the Docker socket. Neither adds a shell path to the engine.
  - **Why:**
    - it covers what btool catches for the allowed keys, more strictly, since it blocks before deploy;
    - it adds no attack surface;
    - it works the same on the lab and in the judges' Docker setup;
    - the allowlist is a Must guardrail anyway.
  - **Revisit:** add a sidecar only if Phase 2–3 runs find a config error that Splunk accepts silently and the allowlist misses.
  - **Phasing:** the allowlist starts in Phase 2 with the index-time keys, and grows in Phases 3 and 4.

## Q8. Ingest path

- **Why it matters:** `data/inputs/oneshot` reads a file **on the Splunk host**, which needs the same shared volume as Q6A. `receivers/simple` takes the data in the POST body.
- **How:** `probe_splunk` posts three lines in one request and reports whether they became 1 or 3 events. Then repeat Q3's test on this path, to confirm `LINE_BREAKER` and `TIME_FORMAT` from the test sourcetype apply.
- **Expectation:** `receivers/simple` goes through the full parsing pipeline, so line breaking and timestamps apply. If the result shows 1 event, use oneshot from the Q6 shared volume instead.
- **Result (2026-10-27):** `probe_splunk`, with the deploy token posting to `pw_probe` and the search token counting:
  ```
  receivers/simple: posted 3 lines, indexed 3 events (line breaking applied)
  ```
  This proves the default line breaking runs on this path. It does not yet prove that a **custom** test sourcetype's `LINE_BREAKER`, `TIME_FORMAT` and `TZ` apply right after a reload. That is Q3's test on this same path, after the first add-on install (Q6).
- **Result, custom sourcetype (2026-10-27):** Q3's `probe_install` run used this same path. A test sourcetype's own `LINE_BREAKER`, `TIME_FORMAT` and `TZ` were applied: 3 events with exact `_time` values. See Q3.
- **Decision:** ingest uses `receivers/simple`, with the samples in the POST body, so ingest needs no shared volume. `data/inputs/oneshot` is not used.

## Q9. Deploy role capabilities

- **How:** `probe_splunk` prints the notable capabilities each token has. Start the deploy role with the expectation below, run Q6's install test and ingest, then remove capabilities one at a time until something fails.
- **Expectation:** the role needs:
  - `install_apps`, or `admin_all_objects` on some versions, to install and update apps;
  - `edit_local_apps`, if B were chosen;
  - `rest_apps_management`;
  - ingest rights into `pw_*` (index access, plus `edit_tcp` for `receivers/simple`).

  The search token must have none of these.
- **Warning:** with `install_apps` and `edit_tcp`, the deploy token is effectively an admin token.
  - It can install an app that contains scripts, which runs code on the Splunk host.
  - It can write into any index (for example `receivers/simple?index=main`). Role index settings do not restrict writes.
  - Therefore:
    - the `pw_` check in code is the only guard on the ingest target (T5.1);
    - the deploy token lives only in the orchestrator process. It must never reach an agent, a prompt, the web process or the ledger.
- **Result (2026-10-27, partial):** `probe_splunk` output:
  ```
  search token: user=parsewright_search roles=['parsewright_search'] notable_caps=[]
  deploy token: user=parsewright_deploy roles=['parsewright_deploy'] notable_caps=['admin_all_objects', 'edit_tcp', 'install_apps', 'rest_apps_management']
  search pw_probe: count=0 (should run without error)
  search other indexes: count=0 (expect 0: only pw_* and _internal visible)
  ```
  - **Search token:** it has its own role only and none of the listed capabilities. Searching outside `pw_*` and `_internal` returns 0 events. The role was created with no inheritance, not inheriting `user` as the lab setup above first said, and new users were created without the default `user` role.
  - **Ingest:** without `edit_tcp` the deploy token's `receivers/simple` post was refused with **HTTP 403**. With `edit_tcp`, 3 lines were indexed. **`edit_tcp` is required.**
  - **App install (2026-10-27):** install, update and uninstall work with `admin_all_objects`, `edit_tcp`, `install_apps` and `rest_apps_management`, as shown in Q6's result.
  - **Trim, step 1: `admin_all_objects` is required.** With it removed, `install_apps` alone was not enough. Installing from a path on the host was refused:
    ```
    install v1 with deploy token: refused HTTP 403
    ```
  - **Indexes:** with `indexes_edit` granted, the deploy token could create a `pw_` index, and the search token was refused (403). Even with `admin_all_objects`, though, the deploy token **could not delete** one (403). An engine that creates one index per attempt, as the design first said, would leave hundreds of indexes behind. Two empty probe indexes were left this way. A later index listing no longer showed them, so nothing was left to remove.
  - **Trim, step 2:** with `rest_apps_management` and `indexes_edit` both removed, the full install probe still passed against the shared `pw_test` index:
    ```
    deploy token: user=parsewright_deploy roles=['parsewright_deploy'] notable_caps=['admin_all_objects', 'edit_tcp', 'install_apps']
    test index: pw_test (exists: True)
    install with search token: refused HTTP 403 (good)
    install v1 with deploy token: ok
    ingest right after install, no reload: 3 events (expect 3: LINE_BREAKER applied), _time matches TIME_FORMAT+TZ
    after v2: v1 stanza present=False, v2 stanza present=True (full replace)
    install probe: PASS
    ```
  - The probe now reports a rejected token's shape (length, part count, user, expiry) without printing it. A pasted-twice deploy token was found this way.
- **Decision (2026-10-27, OWNER):**
  - **One shared test index:** `PARSEWRIGHT_TEST_INDEX`, for example `pw_test`.
    - An admin creates it once. The engine never creates or deletes indexes, so `indexes_edit` is **removed** from the deploy role.
    - Each job and attempt is identified by its sourcetype, `<st>__test_<job>_a<attempt>`.
    - Every Validator search filters on that exact sourcetype. Phase 4 adds an adversarial test that fails if any Validator search lacks the filter.
    - Code still rejects any ingest target that isn't a `pw_` index.
  - **Size, not age, limits the index.** Set a size cap (`maxTotalDataSizeMB`), not an age-based retention (`frozenTimePeriodInSecs`). Sample events carry historical timestamps, so an age-based limit could freeze them before the Validator reads them.
  - **Final deploy role:** `admin_all_objects`, `edit_tcp`, `install_apps`, with allowed indexes `pw_*`. It is near-admin, as the warning above expected, and accepted for the lab because:
    - the token lives only in the orchestrator process;
    - code checks every app name (`TA-parsewright-…__test_…`) and every ingest target (`pw_`) before any call;
    - the threat model lists it as a residual risk.

## Q10. CIM add-on and index macros

- **How:**
  1. Install the Splunk Common Information Model add-on from Splunkbase.
  2. In its setup, or under Settings → Advanced search → Search macros, add `pw_*` to `cim_Authentication_indexes`, `cim_Network_Traffic_indexes` and `cim_Web_indexes`.
  3. Verify with `| tstats summariesonly=false count from datamodel=Authentication where index=pw_probe`, which should run without error (count 0 is fine).
- **Result (2026-10-27):** the owner installed the CIM add-on and edited the macros. Checked with the **search token**:
  ```
  cim_Authentication_indexes: definition='(index=pw*)'
  cim_Network_Traffic_indexes: definition='(index=pw*)'
  cim_Web_indexes: definition='(index=pw*)'
  datamodel Authentication on pw_test: ran ok, count=0
  datamodel Network_Traffic on pw_test: ran ok, count=0
  datamodel Web on pw_test: ran ok, count=0
  ```
  - The search role can read the macros and run all three data models.
  - The macros say `pw*`, not `pw_*`, so they would also match a non-test index whose name starts with `pw`. That is harmless for Parsewright, because the search role can only see `pw_*` anyway, but `pw_*` is the exact form.
  - Phase 10's bootstrap script writes `(index=pw_*)`.
- **Decision:** none needed; this is a lab prerequisite. Phase 10's bootstrap script automates it for judges.

## Q11. In-place updates and `local/` (Phase 7)

- **Why:** a parser update replaces a promoted TA in place. The design says `local/` (admin overrides) is kept and never written, and that the review flags overrides the patch collides with. Neither had been tested.
- **How:** `scripts/probe.sh update`.
  1. Install a throwaway test add-on v1.0.0 and check its timestamps.
  2. Write an admin-style override into its `local/` over REST (`TZ` and one extraction). This probe is the only place Parsewright writes `local/`.
  3. Reinstall a v1.1.0 with `update=true`: a new `TIME_FORMAT` for the same sourcetype and one new extraction.
  4. Read the effective settings in the app's context, then ingest new-format lines with no reload.
- **Result (2026-10-28):**
  ```
  install v1: ok
  v1 timestamps correct: True
  after admin edit: EXTRACT-local present=True, TZ=Pacific/Chatham
  reinstall v2 with update=true: ok
  installed version: 1.1.0 (expect 1.1.0)
  local/ kept after update: True (EXTRACT-local present=True, TZ=Pacific/Chatham: local still overrides default's UTC)
  v2 default applied: TIME_FORMAT='%d/%m/%Y %H:%M:%S', EXTRACT-b present=True
  changed TIME_FORMAT on the existing sourcetype applied, no reload: True
  update probe: PASS
  ```
  - `update=true` replaces `default/` and keeps `local/`; a `local/` value still wins over the new default. This is exactly the case the review must flag: an old `TZ` in `local/` would hide the fix.
  - A changed index-time setting on an existing sourcetype applies to the next ingest with no reload (closes the open half of Q3).
  - `configs/conf-props/default` returns 404 in every namespace, so the `[default]` stanza cannot be read as a baseline over REST.
- **Decision:**
  - Updates are promoted in place with `update=true`, only over a TA the registry lists, at the version the registry expects.
  - Overrides are found by comparing the effective settings (app context) with what the production TA's own `default/` sets. For a key the TA does not set, the comparison is against Splunk's documented `props.conf` defaults, kept in code.
