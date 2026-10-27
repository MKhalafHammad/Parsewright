# Lab findings (Phase 1)

> Every open question from [design.md](design.md), plus those the build plan added. Each has how to test it, the result and the decision it causes. **Expectation** lines are unverified hypotheses written before testing; only **Result** lines count. Never paste tokens, passwords, real hostnames or IPs here.

## Summary

| Q | Question | Answered by | Status | Decision |
| --- | --- | --- | --- | --- |
| Q1 | Does the Meta Model API support `response_format` JSON schemas, or do we need a forced tool call? | `probe_llm` | Answered 2026-10-27 | `response_format` with a strict JSON schema |
| Q2 | What is "contributor mode"? | Meta docs / hackathon guide | Pending OWNER | |
| Q3 | Do index-time settings apply to the next ingest right after a reload? | `probe_install` | Answered 2026-10-27 for a new sourcetype; changed settings on the same sourcetype untested | Applied right after install, no reload or restart needed |
| Q4 | Which edge cases are in scope? | Decision | Pending OWNER | |
| Q5 | Four agents, or merge Extraction and CIM mapper into three? | Decision | Pending OWNER | |
| Q6 | Deploy path: install a package, or write stanzas over REST? | `probe_install` + decision | Answered 2026-10-27 | A: package install via `apps/local`; `update=true` is a full replace |
| Q7 | How to run `btool check` without shell access to Splunk | Decision | Pending OWNER | |
| Q8 | Ingest path: does `receivers/simple` apply line breaking and timestamps? | `probe_splunk` + `probe_install` | Answered 2026-10-27 | `receivers/simple` |
| Q9 | Which capabilities does the deploy role need? | `probe_splunk` + manual | Partly answered 2026-10-27: ingest needs `edit_tcp`; app-install trim pending Q6 test | |
| Q10 | CIM add-on installed, `pw_*` in the CIM index macros | Manual lab step | Pending OWNER | |

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
- **Result:**
- **Decision:** standard mode unless the result says otherwise.

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
- **Decision (OWNER):**

## Q5. Four agents or three

- **Recommendation:** keep four, as the design has them. Separate context and ownership are what make failure routing and "agents never grade themselves" clear. Merging saves one prompt but blurs which agent owns a failing check. Revisit only if Phase 3 runs late.
- **Decision (OWNER):**

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
- **Decision (OWNER):**

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
  - **App install (2026-10-27):** install, update and uninstall work with `admin_all_objects`, `edit_tcp`, `install_apps` and `rest_apps_management`, as shown in Q6's result. The trim is pending: remove `admin_all_objects` first, since it is close to full admin, then `rest_apps_management`, re-running `scripts/probe.sh install` after each.
  - **Not yet tested: creating indexes.** The design ingests each attempt into a fresh index, `pw_<run>_<stage>_<attempt>`. Creating an index over REST needs `indexes_edit`, which the deploy role does not have. Every probe so far used the pre-created `pw_probe`. Decide before Phase 2: grant `indexes_edit`, or pre-create one index per job.
  - The probe now reports a rejected token's shape (length, part count, user, expiry) without printing it. A pasted-twice deploy token was found this way.
- **Decision:** the final capability list is recorded after the Q6 install test and the trim.

## Q10. CIM add-on and index macros

- **How:**
  1. Install the Splunk Common Information Model add-on from Splunkbase.
  2. In its setup, or under Settings → Advanced search → Search macros, add `pw_*` to `cim_Authentication_indexes`, `cim_Network_Traffic_indexes` and `cim_Web_indexes`.
  3. Verify with `| tstats summariesonly=false count from datamodel=Authentication where index=pw_probe`, which should run without error (count 0 is fine).
- **Result:**
- **Decision:** none needed; this is a lab prerequisite. Phase 10's bootstrap script automates it for judges.
