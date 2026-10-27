# Lab findings (Phase 1)

> Every open question from [design.md](design.md), plus those the build plan added. Each has how to test it, the result and the decision it causes. **Expectation** lines are unverified hypotheses written before testing; only **Result** lines count. Never paste tokens, passwords, real hostnames or IPs here.

## Summary

| Q | Question | Answered by | Status | Decision |
| --- | --- | --- | --- | --- |
| Q1 | Does the Meta Model API support `response_format` JSON schemas, or do we need a forced tool call? | `probe_llm` | Pending OWNER run | |
| Q2 | What is "contributor mode"? | Meta docs / hackathon guide | Pending OWNER | |
| Q3 | Do index-time settings apply to the next ingest right after a reload? | Manual lab step | Pending OWNER run | |
| Q4 | Which edge cases are in scope? | Decision | Pending OWNER | |
| Q5 | Four agents, or merge Extraction and CIM mapper into three? | Decision | Pending OWNER | |
| Q6 | Deploy path: install a package, or write stanzas over REST? | Manual lab step + decision | Pending OWNER | |
| Q7 | How to run `btool check` without shell access to Splunk | Decision | Pending OWNER | |
| Q8 | Ingest path: does `receivers/simple` apply line breaking and timestamps? | `probe_splunk` | Pending OWNER run | |
| Q9 | Which capabilities does the deploy role need? | `probe_splunk` + manual | Pending OWNER run | |
| Q10 | CIM add-on installed, `pw_*` in the CIM index macros | Manual lab step | Pending OWNER | |

## Lab setup (OWNER ACTION, once)

1. **Start Splunk:** the lab VM, or `make up` for the Docker stack. Log in to Splunk Web as `admin`.
2. **Create the test index:** in Settings → Indexes, create `pw_probe`.
3. **Create three roles** (Settings → Roles):
   - **`parsewright_search`**
     - Inherits `user`.
     - Indexes searched by default and allowed: only `pw_*` and `_internal`.
     - Remove access to every other index.
   - **`parsewright_deploy`**
     - Inherits nothing.
     - Start with the capabilities in Q9's expectation and trim them after the probe.
     - Allowed indexes: `pw_*`.
   - **`parsewright_drift`**
     - Inherits `user`.
     - Read-only.
     - Search filter set later (Phase 8).
4. **Create three users** (Settings → Users), one per role, each with a long random password you don't keep. Tokens are how they authenticate.
5. **Create the tokens:** Settings → Tokens → enable token authentication, then create one token per user. Paste them into `.env` as `SPLUNK_SEARCH_TOKEN`, `SPLUNK_DEPLOY_TOKEN` and `SPLUNK_DRIFT_TOKEN`.
6. **Point `.env` at Splunk:** set `SPLUNK_HOST` and `SPLUNK_PORT` to the lab's REST address.

## Running the probes (OWNER ACTION)

```bash
set -a; . ./.env; set +a          # load .env into this shell only
.venv/bin/python -m parsewright.tools.probes.probe_llm
.venv/bin/python -m parsewright.tools.probes.probe_splunk
```

Against the Docker stack, port 8089 is not published to your machine (by design). Run the Splunk probe inside the Compose network instead:

```bash
docker run --rm --network parsewright_default --env-file .env -e SPLUNK_HOST=splunk \
  -v "$PWD/engine:/engine" -w /engine python:3.12-slim \
  sh -c "pip install -q . && python -m parsewright.tools.probes.probe_splunk"
```

Both probes print only usernames, roles, capability names, counts and pass/fail lines; they never print tokens or prompts. Paste their output under **Result** below.

## Q1. Structured output from the Meta Model API

- **Why it matters:** every agent returns a schema-validated object. The LLM client (Phase 2) needs to know which mechanism to use.
- **How:** run `probe_llm`. It sends one tiny request with `response_format: json_schema` and, if that fails, one with a forced tool call. It prints which mode works and the token count.
- **Expectation:** at least one mode works. If neither does, Phase 2 falls back to JSON in plain text, validated by Pydantic, with the "bad output" retry cap of 2.
- **Result:**
- **Decision:**

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
- **Result:**
- **Decision:**

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
- **How to verify:** install a trivial `TA-parsewright-acme-probe__test_probe.tgz` with `parsewright_deploy`'s token, then confirm it appears in `apps/local`. Then try the same with the search token, which must be refused.
- **Result:**
- **Decision (OWNER):**

## Q7. `btool check` without shell access

`btool` runs on the Splunk host. The tempting fix is to mount the Docker socket into the engine so it can `docker exec`, but that hands the engine root on the host (threat T7.5), so **it is ruled out**.

- **Options:**
  1. **Local check in the engine:** the escaping writer guarantees syntax. The gate checks keys and values against an allowlist of known settings with valid types. Then the deploy reload's messages are read back through REST (`/services/messages`, splunkd warnings on `_internal`).
  2. **A minimal sidecar in the Splunk container**, exposing only "run `btool check` for app X". It is more moving parts and a new attack surface.
- **Recommendation:** option 1. The writer plus allowlist cover what `btool check` catches for the keys we allow (unknown keys, bad stanzas), and Splunk's own warnings after reload catch the rest. Record the deviation from the design's "`btool check` before deploy" in design.md.
- **Decision (OWNER):**

## Q8. Ingest path

- **Why it matters:** `data/inputs/oneshot` reads a file **on the Splunk host**, which needs the same shared volume as Q6A. `receivers/simple` takes the data in the POST body.
- **How:** `probe_splunk` posts three lines in one request and reports whether they became 1 or 3 events. Then repeat Q3's test on this path, to confirm `LINE_BREAKER` and `TIME_FORMAT` from the test sourcetype apply.
- **Expectation:** `receivers/simple` goes through the full parsing pipeline, so line breaking and timestamps apply. If the result shows 1 event, use oneshot from the Q6 shared volume instead.
- **Result:**
- **Decision:**

## Q9. Deploy role capabilities

- **How:** `probe_splunk` prints the notable capabilities each token has. Start the deploy role with the expectation below, run Q6's install test and ingest, then remove capabilities one at a time until something fails.
- **Expectation:** the role needs:
  - `install_apps`, or `admin_all_objects` on some versions, to install and update apps;
  - `edit_local_apps`, if B were chosen;
  - `rest_apps_management`;
  - ingest rights into `pw_*` (index access, plus `edit_tcp` for `receivers/simple`).

  The search token must have none of these.
- **Result** (final capability list):
- **Decision:**

## Q10. CIM add-on and index macros

- **How:**
  1. Install the Splunk Common Information Model add-on from Splunkbase.
  2. In its setup, or under Settings → Advanced search → Search macros, add `pw_*` to `cim_Authentication_indexes`, `cim_Network_Traffic_indexes` and `cim_Web_indexes`.
  3. Verify with `| tstats summariesonly=false count from datamodel=Authentication where index=pw_probe`, which should run without error (count 0 is fine).
- **Result:**
- **Decision:** none needed; this is a lab prerequisite. Phase 10's bootstrap script automates it for judges.
