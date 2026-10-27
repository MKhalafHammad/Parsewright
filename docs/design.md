# Parsewright — Design Overview

> Source of truth for development. Place at `docs/design.md`. Last updated Oct 27, 2026.

## Overview

Parsewright turns raw sample logs into a tested, CIM-compliant Splunk add-on (TA), deployed to Splunk Enterprise and packaged as a `.tgz`, with an AI agent doing the parsing work and Splunk itself verifying the result.

**Problem.** Every new data source in a SOC needs a parser: line breaking, timestamps, field extractions and CIM mapping. Writing and testing `props.conf` and `transforms.conf` by hand takes hours per source, and mistakes at index time corrupt data permanently.

**Solution.** A team of Muse Spark agents studies the logs, writes the TA stage by stage, deploys it to a standalone Splunk Enterprise instance, ingests the samples into a test index, and fixes its own work until fixed validation searches pass. A human approves before anything is promoted.

**Hackathon fit.** Meta Global AI Developer Hackathon, "Build for Your World" track: a problem known firsthand from daily Splunk and SOC work.

**Meta models.**

- Muse Spark (`muse-spark-1.3`, standard mode) via the Meta Model API for all agent reasoning
- Muse Spark Open for an on-prem mode: same code, a different `LLM_BASE_URL`, so logs never leave the network
- Muse Code to speed up the build

**One-line pitch:** from raw log to CIM-compliant add-on in minutes instead of hours, verified by Splunk, not by the model.

## Scope and design principles

The hackathon build targets one standalone Splunk Enterprise instance, four log formats and three CIM data models, polished rather than broad.

| In scope | Out of scope (for now) |
| --- | --- |
| Splunk Enterprise standalone (all-in-one) | Splunk Cloud, clusters, deployer, forwarders |
| Formats: JSON, key=value, syslog, CSV | XML, binary, exotic vendor formats |
| CIM: Authentication, Network_Traffic, Web | Other data models |
| TA in `/opt/splunk/etc/apps/TA-parsewright-<vendor>-<product>` | Production rollout across a fleet |
| Synthetic logs with a truth manifest | Client or real customer logs |
| Logs supplied by upload or drop folder | Automatic discovery of unparsed data inside Splunk (dropped: damaged samples, production data exposure) |
| Dedicated inputs and shared syslog feeds (routing by index-time sourcetype rename) | Writing inputs.conf (left to the input owner) |
| Parser updates and drift monitoring for TAs built by Parsewright | Updating TAs not built by Parsewright (needs an overlay TA and app precedence handling) |

**Principles**

1. **The model reasons, the tools act, Splunk judges.** Agents propose configs; code deploys them; fixed SPL checks decide pass or fail.
2. **Agents never grade themselves.** An agent may search to investigate, but only the Validator moves the run forward.
3. **Orchestrated by code, not by an AI manager.** A deterministic state machine owns order, retries and budgets.
4. **Fresh, focused context per agent.** Agents never share a conversation; each gets a curated package from the run ledger.
5. **Score only what is achievable.** CIM checks count required fields and fields the source actually has, never fields the log never carried.
6. **Stop honestly.** When a budget runs out, the run ends with a clear report of what it could not solve.
7. **Human in the loop** at profile review and before promotion.

## System architecture

Three layers: a web UI, a FastAPI backend holding the orchestrator, agents and actions, and a standalone Splunk Enterprise instance reached only over REST.

```
┌──────────────────────────────────────────────────────────────────┐
│ Web UI (Next.js)                                                 │
│ Upload samples · live ledger · profile review · approve/reject   │
└───────────────────────────────┬──────────────────────────────────┘
                                │ HTTP + server-sent events
┌───────────────────────────────▼──────────────────────────────────┐
│ Backend (FastAPI)                                                │
│                                                                  │
│  Orchestrator (deterministic code)  ◄──►  Jobs + ledger          │
│  Worker pool · one state machine per job  (PostgreSQL)           │
│  Routes failures back to the owning agent                        │
│        │                         │                               │
│        ▼                         ▼                               │
│  Muse Spark agents          Orchestrator-only actions            │
│  Profiler · Index-time      Guardrail gate                       │
│  Extraction · CIM mapper    TA builder · deploy · ingest         │
│  (+ Router, Drift Analyst)  Validator (fixed SPL, no AI)         │
│  Tools: run_search,                                              │
│         test_regex                                               │
└────────┬─────────────────────────┬───────────────────────────────┘
         │ read-only search        │ deploy · ingest · validate
┌────────▼─────────────────────────▼───────────────────────────────┐
│ Splunk Enterprise standalone                                     │
│ /opt/splunk/etc/apps/TA-parsewright-* · pw_* test indexes        │
│ REST :8089 with scoped tokens (search, deploy, drift)            │
└──────────────────────────────────────────────────────────────────┘
```

Agents only reason and search read-only; every write to Splunk goes through orchestrator code and the guardrail gate. The LLM endpoint is the Meta Model API by default, or a self-hosted Muse Spark Open by changing `LLM_BASE_URL`.

## AI agent architecture

Four core Muse Spark agents, plus an optional Router for shared feeds and a Drift Analyst for format changes (see Drift pipeline), each own one part of the TA, return a strict schema-validated object, and are judged by their own checks. Agents never talk to each other or deploy anything.

| Agent | Job | Owns (writes) | Output | Judged by |
| --- | --- | --- | --- | --- |
| Profiler | Understand the logs | Nothing | `LogProfile` | Human profile review |
| Index-time | Split events and timestamp them | `LINE_BREAKER`, `SHOULD_LINEMERGE`, `TIME_PREFIX`, `TIME_FORMAT`, `MAX_TIMESTAMP_LOOKAHEAD`, `TZ`, `TRUNCATE` | Index-time stanza | Event count, parser warnings, `_time` accuracy |
| Extraction | Get the fields out | `KV_MODE`, `EXTRACT-`, `REPORT-` + `transforms.conf` | Search-time stanza | Field coverage, greedy-regex and duplicate checks |
| CIM mapper | Normalize to CIM | `FIELDALIAS`, `EVAL`, lookups, `eventtypes.conf`, `tags.conf` | CIM config | Required fields, allowed values, child datasets |

**LogProfile contents:** format, multiline flag, timestamp example and format candidates, timezone hints, vendor/product guess, sourcetype name, field inventory with coverage, event categories, target CIM models. Every later stage builds on it, and its field inventory defines what CIM fields are achievable.

### Context each agent receives

| Agent | Gets | Does not get |
| --- | --- | --- |
| Profiler | Raw samples | Anything else |
| Index-time | Profile, samples, current index-time stanza, its own past failures | Extraction or CIM work |
| Extraction | Profile, correctly broken events from Splunk, current extraction config, its own past failures | Index-time history |
| CIM mapper | Profile, extracted fields with real values, CIM spec for the target model, its own past failures | Raw regex attempts |

The TA files on disk are the source of truth: each attempt reads them fresh rather than relying on the agent's memory of what it wrote.

### Tools per agent

| Agent | `run_search` (read-only, scoped) | `test_regex` (local) | Deploy, reload, ingest |
| --- | --- | --- | --- |
| Profiler | No | Yes | No |
| Index-time | Yes | Yes | No |
| Extraction | Yes | Yes | No |
| CIM mapper | Yes | No | No |
| Orchestrator code | n/a | n/a | Yes, only here |

`test_regex` lets an agent check a regex against sample lines before proposing it, so many bad regexes never reach Splunk. The 1M-token context lets the CIM spec and large samples sit in one prompt without retrieval.

## Orchestrator state machine

A run moves through eight states in a fixed order; the agent stages each loop until their checks pass, and every transition is saved to PostgreSQL before the next step.

```
Created ─► Profiling ─► Profile review ─► [Routing*] ─► Index-time ─► Extraction ─► CIM mapping ─► Awaiting approval ─► Promoting ─► Done
           (agent)      (human)           (agent)       (agent,       (agent,       (agent,         (human)              (.tgz)
                                                         retry ≤5)     retry ≤5)     retry ≤5)

* Routing runs only for shared feeds.

End states:
  Done           TA ready
  Stage failed   any agent stage spent its budget; honest report
  Rejected       human rejected; TA rolled back
  Error          from any state; unrecoverable infrastructure failure
```

For shared feeds, an optional Routing state runs between Profile review and Index-time. Any agent stage that spends its budget goes to Stage failed. Two extra rules apply inside the stages: after a pass, earlier stages' checks re-run to catch regressions, and a later stage may send the run back to an earlier one once per run (for example, missing fields caused by merged events go back to Index-time).

Saving on every transition gives crash recovery (resume from the last state), the live UI (it reads state and ledger), and a full audit trail for the report and the demo.

## End-to-end workflow

A run goes from upload to an approved `.tgz` in eight steps; steps 4 to 6 each repeat an inner loop until their checks pass or their budget runs out.

1. **Intake.** Samples arrive by upload or drop folder. A job is queued (duplicates rejected), and a free worker claims it.
2. **Profile.** The Profiler reads the samples and returns a `LogProfile`.
3. **Profile review.** The user confirms or corrects vendor, timezone, event categories and CIM targets. Can be auto-approved for unattended runs.
4. **Index-time stage.** Line breaking and timestamps, preceded by the Routing stage when the feed is shared (see Mixed feeds).
5. **Extraction stage.** Search-time fields.
6. **CIM stage.** Aliases, evals, lookups, eventtypes, tags.
7. **Approval.** The user reviews raw vs parsed events side by side (each extracted value highlighted in the raw line, `_time` next to the raw timestamp) and a raw value → field → CIM field → normalized value table, plus the scores and final configs. They approve, reject (TA rolled back), or correct a mapping, which sends the job back only to the owning stage with the correction as evidence. Corrections are saved as future training examples.
8. **Promote.** The TA is packaged as `TA-parsewright-<vendor>-<product>.tgz` and kept installed for real use.

### Inner loop for every stage attempt

1. **Generate:** the stage's agent gets its curated context and returns its config (schema-validated).
2. **Gate:** guardrails check it: key allowlist, `btool check`, regex safety, scope. *(2026-10-27: `btool check` is replaced by a key allowlist with typed values and bounds, run before deploy, plus a post-install check: any splunkd warning about the test add-on fails the attempt, and the warning becomes evidence. splunkd does not warn about unknown or misspelled keys at runtime, so the allowlist is the only syntax control; the post-install check catches parsing warnings. No shell, sidecar or Docker socket. See [lab-findings.md](lab-findings.md), Q7.)*
3. **Deploy:** write the new TA version to `/opt/splunk/etc/apps/TA-*/default/` via REST under its test identity (see Test identity) and reload configs (no restart). *(2026-10-27: done by installing the complete `.tgz` through the `apps/local` endpoint with `update=true`, from a shared packages folder; never through the `configs/conf-*` endpoints. See [lab-findings.md](lab-findings.md#q6-deploy-path), Q6.)*
4. **Ingest:** oneshot the samples into a fresh index, `pw_<run>_<stage>_<attempt>`, then wait until the event count is stable. *(2026-10-27: ingest posts the samples to `receivers/simple`, not oneshot. A newly installed sourcetype's index-time settings apply to the very next ingest with no reload or restart. All test ingests go to **one shared index**, `PARSEWRIGHT_TEST_INDEX` (for example `pw_test`), created once by an admin. The engine never creates or deletes indexes. Each attempt has its own sourcetype (see Test identity), and every Validator search filters on that exact sourcetype, so attempts and jobs never mix. See [lab-findings.md](lab-findings.md), Q3, Q8 and Q9.)*
5. **Validate:** run that stage's fixed SPL checks, plus a quick regression re-run of earlier stages' checks.
6. **Decide:** pass moves to the next stage; fail returns to the same agent with evidence (expected, actual, up to 3 failing events).

### Failure handling

| Failure | Example | Response | Counts against budget |
| --- | --- | --- | --- |
| Bad output | Invalid JSON from the model | Ask again, same context | Separate cap of 2 |
| Guardrail block | Tried to write `inputs.conf` | Retry with the block reason | Yes |
| Infra error | Splunk REST timeout | Retry with backoff, no model call | No |
| Validation fail | `_time` off by 10,800 s on every event | Retry with evidence | Yes |
| Earlier-stage cause | Fields missing because events merged | Backtrack to the owning stage, at most once per run | Yes |

**Budgets:** 5 attempts per stage, a token/cost ceiling per run, 15 minutes wall-clock. The first limit hit ends the run in `STAGE_FAILED` with an honest report.

## Test identity

Every test deploy runs under a separate app name and a separate sourcetype name, so untested config never parses production data; the real names are restored by code only at promotion.

**Why.** `props.conf` stanzas are keyed by sourcetype. A test TA reusing the real sourcetype would merge with the installed TA, and Splunk precedence would decide which settings parse live data. The same applies to routing: a test rule attached to the real `[syslog]` stanza would reroute production events mid-test.

| Item | Production name | Test name |
| --- | --- | --- |
| App | `TA-parsewright-fortinet-fortigate` | `TA-parsewright-fortinet-fortigate__test_<job>` |
| Sourcetype (every stanza, eventtype and search in the copy) | `fortinet:fortigate:traffic` | `fortinet:fortigate:traffic__test_<job>_a<attempt>` |
| Generic sourcetype for routing tests | `syslog` | `syslog__test_<job>` |
| Transforms | `parsewright_<job>_…` | Same prefix plus `__test` |

*(2026-10-27: the sourcetype also carries the attempt number, `__test_<job>_a<attempt>`. Every attempt is then a new sourcetype, which is the case the lab proved applies without a reload (Q3). It also separates attempts inside the one shared test index.)*

**Applies to** new builds and parser updates alike: samples are ingested into the test index with the test sourcetype, and test apps are removed with the job's other test resources.

**At promotion.** Code, never the agent, renames the tested package back to the real names. The rename is deterministic, but the final file differs from the tested one, so the ledger records both hashes linked by the rename, approval covers the pair, and a smoke test runs right after promotion.

## Uploads

Each job takes sample logs from one log source, raw as the source writes them, plus an optional short form; the model learns from a sample while the Validator tests on the whole file.

**What to upload**

- One log source per job (e.g. a FortiGate traffic log); one or several files of that source
- Formats in scope: JSON, key=value, syslog, CSV, as `.log`, `.txt`, `.json`, `.csv` or single-file `.gz`; no archives
- Raw as written by the source, not re-saved in Excel; for a shared feed, upload the whole mixed feed so the negative routing test has non-target events
- Minimum about 50 events; maximum 10 MB per job, measured after decompression
- Content checked on upload (text, UTF-8, line endings), not just the extension

**Optional form (pre-fills profile review)**

| Field | Why |
| --- | --- |
| Vendor / product | Naming and CIM mapping |
| Timezone of the logs | Prevents the classic +3 h error when logs carry no timezone |
| How logs reach Splunk (file monitor, syslog, HEC) | Syslog adds a header that changes line breaking and timestamps |
| Sourcetype name | Otherwise the Profiler proposes `vendor:product:type` |
| Target CIM model | Or auto-detect |
| Current sourcetype (e.g. `syslog`, `fw01-2`) | Test data is ingested exactly as production receives it |
| Shared feed? | Yes runs the Routing stage |

**Holdout test.** The agents see about 200 lines picked to cover each event type; the Validator ingests the full file. The parser is proven on events the model never saw ("learned from 200 lines, passed on 8,000").

**Drop folder.** Each new subfolder is one job: the log files plus an optional `job.yaml` with the form fields. Symlinks are never followed.

**Getting samples out of Splunk** (when the user has no original file): a plain event search with `| head 500 | reverse`, then Export → Raw Events (or `splunk search … -output rawdata`, or the REST export endpoint with `output_mode=raw`). Before using it, check `max(len(_raw))` and `max(linecount)`: events cut at 10,000 characters are truncated and unusable. The original file on the forwarder or syslog collector is always the better sample.

**Going live.** For a dedicated input, the approval report ends with the exact `inputs.conf` change (e.g. `sourcetype = fortinet:fortigate:traffic` on the input now sending `fw01-2`). Parsewright never writes inputs itself.

**Hackathon:** all uploads come from the synthetic generator, which also writes the truth manifest.

## Concurrency and continuous operation

Every unparsed log source becomes one job in a PostgreSQL queue, and a pool of long-running workers processes jobs in parallel, with database locks guaranteeing that no two workers ever handle the same logs.

### Intake

| Source | How jobs are created |
| --- | --- |
| Upload | User uploads samples in the UI |
| Drop folder | New files in a watched folder |

### No two workers on the same logs

1. **Claim with `FOR UPDATE SKIP LOCKED`:** a worker atomically sets a queued job to running with its `worker_id` and a lease; other workers skip locked rows.
2. **Duplicate prevention at intake:** a unique constraint on the source key (host + source path, or vendor/product) for active jobs, plus a content hash of the samples. A repeat upload points to the existing job.
3. **Unique sourcetype and TA name per job:** `props.conf` stanzas are keyed by sourcetype, so two TAs defining the same sourcetype would merge unpredictably.

### Operation never stops

| Situation | Behaviour |
| --- | --- |
| Job waits for human review | Worker releases it and takes the next job; the job is requeued when the human acts |
| Job spends its budget | Only that job ends in `STAGE_FAILED` |
| Worker crashes | Lease (~2 min) expires; another worker resumes from the last saved state |
| Worker is slow but alive | Heartbeat renews the lease |
| Service restarts | Workers run with an auto-restart policy; queued jobs persist in PostgreSQL |
| Production data | Untouched: reload not restart, testing only in `pw_*` indexes |

### Shared limits

- **Splunk writes** (app install, reload) run under one global lock, one job at a time; LLM calls and validation searches run in parallel.
- **Worker count** sized to Splunk's concurrent search limit: start with 3 to 4 on the lab VM.
- **LLM** concurrency cap plus a per-job token budget, to protect rate limits and the $150 credits.

### Credit protection

Credits are spent only on jobs someone started, and always inside hard budgets.

| Control | What it prevents |
| --- | --- |
| Cost estimate shown before a job starts | Surprise spend on a large sample |
| Smart sampling, capped at about 200 lines covering each event type | Sending whole log files to the model |
| Duplicate check by content hash | Paying twice for logs already parsed; the earlier result is reused |
| Per-job token budget | One stubborn source draining credits |
| Global daily budget and kill switch | Runaway spend; workers stop claiming jobs and the UI shows why |
| Spend limit on the Meta billing page | Anything the code misses |

**Demo:** drop four log files at once; the board shows four jobs in parallel, one pausing for review while the others continue.

## Mixed feeds and sourcetype assignment

Parsing only works once events carry the right sourcetype, so Parsewright also handles how events get it, including shared feeds where many vendors arrive under one generic sourcetype such as `syslog`.

Every event in Splunk already has a sourcetype, often a meaningless one: set generically in `inputs.conf` (`syslog`), matched by a pretrained type, or invented from the file name (`fw01-2`, `fw01-too_small`).

### Two cases

| Case | Example | What Parsewright does |
| --- | --- | --- |
| Dedicated input | A forwarder monitoring `/var/log/remote/fw01/` only | No agent work: the approval report ends with the exact `inputs.conf` change to copy, e.g. `sourcetype = fortinet:fortigate:traffic` |
| Shared feed | UDP/TCP 514 with `sourcetype = syslog` carrying FortiGate, Cisco, Palo Alto and Linux | Runs the Routing stage to split the target vendor out by index-time rename |

Parsewright never writes `inputs.conf` itself; changing inputs stays with the person who owns them.

### Routing config the agent produces

```ini
# props.conf
[syslog]
TRANSFORMS-parsewright_route_fgt = parsewright_route_fortigate

# transforms.conf
[parsewright_route_fortigate]
REGEX = devid="?FG[0-9A-Z]+
DEST_KEY = MetaData:Sourcetype
FORMAT = sourcetype::fortinet:fortigate
```

### Two traps the agents must handle

1. **The new sourcetype's index-time settings do not apply to routed events.** Splunk breaks events and extracts timestamps before the routing transform runs, using the original `[syslog]` rules. Only search-time settings of the new sourcetype take effect. So for routed data, index-time settings go in a `[host::...]` or `[source::...]` stanza, or the Index-time agent confirms the generic parsing already handles the data (usually true for single-line syslog).
2. **A broad regex steals other vendors' events.** The rule sits on the shared stanza and touches all data in the feed, so misrouting damages other teams' data.

### Routing stage

An optional stage between Profile review and Index-time, run only when the feed is shared. The Router agent owns the routing regex and transform; it gets the profile, the mixed-feed sample and its own past failures, and may use `run_search` and `test_regex`.

| Check | How | Pass when |
| --- | --- | --- |
| Positive routing | Ingest the mixed sample as the generic sourcetype; count target events by sourcetype | 100% of target events carry the new sourcetype |
| Negative routing | Count non-target events that were renamed | Exactly 0 |
| Index-time on routed data | `_time` and event count checks on the routed events | Same rules as the Index-time stage |

The negative test needs the whole mixed feed, not only the target device, so the upload includes it (or the generator produces a synthetic multi-vendor feed with a manifest of which line belongs to which vendor).

### Upload form additions

| Field | Effect |
| --- | --- |
| Current sourcetype (e.g. `syslog`, `fw01-2`) | Used to ingest test data exactly as production receives it |
| Shared feed? | No: Case 1, `inputs.conf` instruction only. Yes: Routing stage runs |

### Guardrail exception

The key allowlist normally blocks touching generic stanzas. One narrow exception: a `TRANSFORMS-` entry on the generic stanza is allowed only when its transform has `DEST_KEY = MetaData:Sourcetype`. Routing becomes possible; nothing else on the shared stanza is.

**Demo:** upload one mixed syslog feed with four vendors; Parsewright splits it into four sourcetypes, parses each, and proves 0 events were misrouted. Build this after the four core stages work.

## Parser updates

When a log format changes, an update job patches the existing TA with the smallest change that works, and must prove that both the old and the new format still parse, because after a firmware upgrade both usually coexist for a while.

**TA registry.** Every TA that Parsewright builds is stored with its versions, original samples, truth manifest and baseline. The old samples become the regression set, so they are kept for as long as the TA exists.

**Update flow**

1. **Select and upload.** Pick a registered TA and provide new-format samples, by upload or automatically from the drift pipeline.
2. **Diagnose, no AI.** The current TA is tested on the new samples with the normal Validator, producing a drift report (e.g. timestamps fail, `srcip` renamed `src_ip`, new action value `deny-policy`). If everything passes, the job ends with zero credits spent.
3. **Patch mode.** Only agents owning failing checks run. Each gets the current config, the drift evidence and the instruction to make the minimal change (add a timestamp format, extend a regex), never a rewrite.
4. **Regression.** The patched TA must pass on the old registry samples and the new samples. Breaking the old format rejects the attempt with evidence.
5. **Review.** Line-by-line diff against the production version, raw vs parsed for an old and a new event, version bump in `app.conf` (e.g. 1.2.0 → 1.3.0), hash-bound approval, rollback to the exact previous version.

**Promotion of an update.** The app is updated in place via REST: `default/`, `metadata/` and `lookups/` are replaced; `local/` (admin overrides) is kept and never written by Parsewright; the previous version stays in the registry for rollback. Before promotion, Parsewright checks the installed TA's `local/` files: if any override a setting the patch changed (e.g. an old `TIME_FORMAT` in `local/props.conf`), the review flags that the fix will not take effect until a human updates or removes the override. Search-time changes apply to past events immediately; index-time changes apply only to data indexed after the reload.

**Job type:** update, with states Diagnose → failing stages only → Regression → Approval → Promote.

**Out of scope:** updating TAs not built by Parsewright. Editing a Splunkbase vendor TA directly is lost on the vendor's next upgrade; the right approach, a separate overlay TA, depends on Splunk app precedence and is left for later.

## Drift pipeline

Parsewright watches the parsers it built: Splunk alerts detect a format change for free, code collects masked samples, a Drift Analyst agent decides whether the change is real, and an update job is created automatically, so the only manual step is approving the fix.

Example used below: a FortiGate firmware upgrade changes the log format at 14:00.

### Steps

0. **Setup at promotion.** The registry stores a baseline (field coverage, CIM values seen, eventtype match rate, volume). Alert searches are installed in a separate Parsewright monitoring app from fixed templates with only the sourcetype and baseline numbers filled in; no agent writes them. Splunk's scheduler runs them (e.g. every 15 minutes); Parsewright spends nothing until one triggers.
1. **Alert fires (14:15).** Splunk's webhook alert action posts TA ID, signal, sourcetype, count and window to FastAPI. The endpoint uses a secret token in the URL and accepts only the Splunk server's address, since the webhook cannot send auth headers.
2. **Dedup and grouping (code).** Signals for a TA with an open drift job attach to it; signals within minutes become one job; a TA closed as noise in the last hour is in cooldown.
3. **Collection (code, no AI).** With a read-only account limited to registered sourcetypes: change point (`timechart span=5m` of failing vs normal), affected hosts (e.g. 7 of 20, a partial rollout), failing samples grouped by shape, normal events from the same window, truncation check. Values are masked with consistent, format-preserving fakes, so regexes built from them still hold; the masking map also gives partial ground truth.
4. **Drift Analyst agent.** Gets only the evidence bundle and one narrow tool, `fetch_more_samples(pattern, n)`, run by the collector with masking. Returns verdict, change start, affected hosts, summary, stages affected, representative samples and confidence. Code also requires sustained volume (more than N events over more than M minutes) before a real-change verdict counts.
5. **Update job created.** New samples from the analyst, old samples from the registry, only the affected stages; then the parser update flow.
6. **Human approval.** Notification (UI badge for the hackathon; email or Slack later); review shows the drift report, the diff, and old and new events passing.
7. **Recovery.** The alerts must go quiet for the next runs, then the job closes as resolved, or reopens with new evidence. The baseline is updated. A damage report states that search-time fixes apply to past events but index-time fixes do not (e.g. "12,340 events indexed 14:02–14:41 have wrong timestamps; re-ingest from source if needed").

### Detection signals

| Signal | Catches |
| --- | --- |
| `DateParserVerbose` warnings for the sourcetype | Timestamp format change |
| Line-breaking warnings for the sourcetype | Event structure change |
| Key field coverage below baseline | Renamed or moved field |
| CIM values outside the allowed set | New vendor values |
| Rising events with no eventtype or tag | New event types |

### Analyst outcomes

| Verdict | Result |
| --- | --- |
| Noise | Closed with explanation; cooldown starts |
| Needs human | Truncated events or low confidence: asks for a raw file upload |
| Real change | Update job created automatically |

### Drift job states

```
SIGNALED → COLLECTING → ANALYZING ─┬→ CLOSED_NOISE
                                   ├→ NEEDS_HUMAN
                                   └→ UPDATE_CREATED → UPDATE_RUNNING
                                        → AWAITING_APPROVAL → PROMOTED
                                        → RECOVERY_CHECK ─┬→ RESOLVED
                                                          └→ REOPENED
```

Same PostgreSQL queue, locking, persistence, budgets and kill switch as build jobs.

### Production access, deliberately narrow

Unlike the dropped discovery idea, drift monitoring only reads sourcetypes Parsewright built, and samples are usually intact because a timestamp or field change leaves `_raw` untouched. Masking (or on-prem Muse Spark Open) applies before any model call.

**Credits:** detection, dedup and collection use none; the Analyst runs once per drift job; the update job runs only affected stages.

**Demo:** the generator feeds a lab production index, switches format at minute 2, and the fix is waiting for approval without anyone touching anything.

## Validation design

The Validator is code plus fixed SPL, no AI: it runs searches through the Splunk Python SDK (`jobs.oneshot`, JSON output) and applies a pass/fail rule to each result.

**Mechanics**

- Wait for indexing: poll `| tstats count where index=<test_index>` until two consecutive polls match.
- Always search `earliest=0`, because samples carry historical timestamps.
- Ground truth comes from the synthetic generator's truth manifest (event count, true epoch per event, true field values). For real logs without a manifest, Splunk's own warnings and consistency checks stand in.

### Index-time checks

| Check | How | Pass when |
| --- | --- | --- |
| Event count | `\| tstats count where index=<idx>` | Equals manifest count |
| Parser warnings | `index=_internal sourcetype=splunkd log_level=WARN` for `DateParserVerbose`, `LineBreakingProcessor`, `AggregatorMiningProcessor` on the test source | Zero |
| Timestamp fallback | Events with abs(`_indextime` − `_time`) < 60 s | Zero |
| Timestamp accuracy | `_time` per event vs manifest epoch | All match |

### Extraction checks

| Check | How | Pass when |
| --- | --- | --- |
| Field coverage | `\| fieldsummary` vs the profile's field inventory | Each field at its expected coverage |
| Greedy regex | Values containing delimiters or outlier lengths | Zero events |
| Duplicates | `mvcount(field) > 1` where single-valued is expected | Zero events |
| Value spot-check | Extracted vs manifest values on a sample | All match |

### CIM checks

| Check | How | Pass when |
| --- | --- | --- |
| Reaches the model | `\| tstats summariesonly=false count from datamodel=<Model> where index=<idx>` | Count equals expected events |
| Required fields | `\| datamodel <Model> <Dataset> search` + count per required field | Every required field the source has equals total |
| Allowed values | e.g. `Authentication.action` not in success, failure, unknown | Zero events |
| Child datasets | Failures land in e.g. `Failed_Authentication` | Counts match manifest categories |

**CIM scoring rule (no Vladiator-style false failures):** a field counts as missing only if CIM expects it *and* the source contains it. The report shows three numbers: required fields passed, available fields mapped, and fields not in the source (informational, no penalty). Required-field lists per dataset are pinned from the CIM documentation in `cim_spec/`, not chosen by the model.

**Lab prerequisite:** include `pw_*` in the CIM index macros (e.g. `cim_Authentication_indexes`) on the lab instance, or CIM checks fail falsely.

**Feedback to the agent** is compact: stage, failed check, expected, actual, up to 3 sample events. Precise evidence such as "+10800 s on 40/40 events" points straight at the fix (a wrong `TZ`).

## Guardrails and security

An AI with write access to Splunk is a risk, so every agent output passes a deterministic gate that checks values as well as keys, the workflow itself is tamper-proof, and every Splunk call uses a narrowly scoped account. Priorities: **Must** for the hackathon, **Should** if time allows, **Later** for production.

### Config safety (keys and values)

| Guardrail | Stops | Priority |
| --- | --- | --- |
| Key allowlist: parsing keys only | `inputs.conf`, `commands.conf`, anything that executes code | Must |
| Block `DEST_KEY = queue` / `nullQueue` | Silent deletion of events | Must |
| Block `_TCP_ROUTING` and `_MetaData:Index` | Data sent to another output or index | Must |
| Block `INGEST_EVAL` and `SEDCMD-` | Permanent index-time changes to `_raw` or fields | Must |
| Min/max bounds on `TRUNCATE`, `MAX_EVENTS`, `MAX_TIMESTAMP_LOOKAHEAD` | Giant events and pipeline memory problems | Must |
| `EVAL-`/`FIELDALIAS-` may not target `index`, `host`, `source`, `sourcetype`, `_time`, `_raw` | Corrupting core fields for every search | Must |
| No `[default]`, no broad `[source::...]` or `[host::*]` | Changing parsing for all data | Must |
| CSV lookups inside the TA only | External lookups that run scripts | Must |
| Routing exception: a `TRANSFORMS-` on a generic stanza only with `DEST_KEY = MetaData:Sourcetype`, and 0 misrouted events in the negative test | Any other change to a shared stanza | Must |
| ~~`btool check` before deploy~~ Key allowlist with typed values before deploy, plus a post-install splunkd-warning check that fails closed: any warning about the test add-on fails the attempt *(2026-10-27, Q7)* | Syntax errors, unknown or mistyped keys | Must |
| Regex catastrophic-backtracking test | Stalling the parsing pipeline | Must |

### TA builder

| Guardrail | Stops | Priority |
| --- | --- | --- |
| Reject newlines in values; one escaping conf writer | A value injecting a new stanza such as `[script://…]` | Must |
| Names match `^[a-z0-9_:-]+$`; code adds the fixed prefix `TA-parsewright-` and the pattern applies only to the vendor and product parts; resolved paths must stay inside the TA folder | Path traversal out of the app | Must |
| Package file allowlist: `default/`, `metadata/`, `lookups/` (CSV), `README`, `app.conf` | `bin/` scripts, `appserver/static` JavaScript in Splunk Web | Must |
| Prefix every transform `parsewright_<job>_`; collision check ~~via `btool`~~ by reading existing transform names over REST (`configs/conf-transforms`) before deploy *(2026-10-27, Q7)* | Overriding another app's global transform name | Must |
| TA named `TA-parsewright-<vendor>-<product>`; refuse if the name exists | Overwriting (and later deleting) a Splunkbase vendor TA | Must |

### Validator integrity (no gaming)

| Guardrail | Stops | Priority |
| --- | --- | --- |
| Flag CIM fields with one constant value where the source varies; every CIM field must trace to a source field or an approved constant | `EVAL-action = "success"` passing the allowed-values check | Must |
| Manifest value checks and provenance shown in review | Unrelated fields aliased just to fill required fields | Must |
| Holdout test on the full file; flag literal sample values in regexes | Regexes overfitted to the sample | Should |
| Agents have no file tools; the builder writes only inside the TA | Agents editing `cim_spec/`, manifests or the Validator | Must |

### Untrusted input

| Guardrail | Stops | Priority |
| --- | --- | --- |
| Logs, form fields and `run_search` results passed as data, never instructions | Prompt injection planting a backdoor config | Must |
| Schema validation of every tool-call argument | Malformed or malicious tool calls | Must |
| Human correction text passed as data | Injection through review comments | Should |
| Cap decompressed size; single-file `.gz` only, no archives | Decompression bombs, zip-slip | Must |
| Content-based file checks (text, UTF-8) | Binary or disguised files | Must |
| Never follow symlinks at intake | A drop-folder link to `/etc/shadow` being read and sent to the model | Should |
| Secret scan of samples; warning banner and masking option for real logs | Passwords or tokens in logs reaching a hosted model | Should |

### Splunk resources

| Guardrail | Stops | Priority |
| --- | --- | --- |
| Per-job and daily byte caps on test ingestion | Test data consuming the Splunk license | Must |
| Size-limited test indexes; cleanup after the job, only of indexes the job recorded creating | Disk exhaustion; deleting resources that existed before | Must |
| Code rejects any ingest target not starting with `pw_` | Test data landing in a real index | Must |
| Search command allowlist (`search`, `stats`, `tstats`, `eval`, `where`, `table`, `fieldsummary`, `head`, …), 50 rows, short timeout. *(2026-10-27: with one shared test index, code owns the base search: an agent supplies only a `|` pipeline appended to `search index=<test index> sourcetype=<own attempt sourcetype>`, and commands that start a new result set are blocked for agents: `tstats`, `metadata`, `metasearch`, `datamodel`, `from`, `inputlookup`, `union`, `append*`, `join`, `multisearch`, `set`. `tstats` stays available to the Validator's fixed SPL only. Threat T1.2.)* | `delete`, `collect`, `dbxquery`, `loadjob`, custom commands, other apps' lookups, reading other jobs' samples | Must |
| Rollback removes every TA file, routing transforms included, and re-runs the negative routing test | A leftover rename transform still affecting production | Must |

### Workflow integrity

| Guardrail | Stops | Priority |
| --- | --- | --- |
| Approval bound to the SHA-256 of the exact `.tgz`; promotion deploys only that hash; any later change needs re-approval | A TA modified between validation, approval and deploy | Must |
| State transitions enforced in the database (`UPDATE … WHERE status = 'awaiting_approval'`) | Skipping validation or approval; replayed approve or promote requests | Must |
| ~~Before ingesting, check the attempt's test index is empty, else recreate it~~ Before ingesting, assert the attempt's sourcetype has 0 events in the shared test index, else bump the attempt number; never reuse a sourcetype, including on resume *(2026-10-27, T4.5)* | Duplicate events after a retried ingest failing the count check | Must |
| On resume after a crash or timeout, read the installed TA version from Splunk and compare hashes before redeploying | Acting on an ambiguous deploy outcome | Must |
| Adversarial regression suite (`nullQueue`, newline injection, path traversal, injected log lines, constant-value gaming) run on every change | Old bypasses returning | Must |
| Ledger records model version, Validator version, CIM spec hash and artifact hash per run | Results that cannot be reproduced | Should |
| Append-only ledger | Edited audit history | Should |
| Timeouts on every Splunk and model call; max 10 tool calls per attempt | Hung workers; agents searching in circles | Must |
| Test identity: separate app and sourcetype names for every test deploy; rename back by code at promotion with both hashes linked and a smoke test | Untested config or routing rules parsing production data during testing | Must |

### Secrets and platform

| Guardrail | Stops | Priority |
| --- | --- | --- |
| `.env` in `.gitignore`, `.env.example`, pre-commit secret scan | Tokens and API keys in the public repo | Must |
| No credentials in prompts; redaction in logs and ledger | Secrets leaking through the model or audit trail | Must |
| Log text rendered only as escaped text; highlights built as React elements | XSS from `<script>` in log lines in the raw vs parsed view | Must |
| Login; approve and promote need an approver role | Anyone reaching the API approving changes | Should |
| High-risk changes (routing on shared stanzas) flagged with a second confirm | Risky approvals looking routine | Should |
| Pinned dependencies with hashes | Supply-chain drift in the public repo | Should |

### Splunk service accounts (token auth)

| Account | Used by | Can |
| --- | --- | --- |
| `parsewright_search` | Agents' `run_search`, the Validator | Search only `pw_*` and `_internal` |
| `parsewright_deploy` | Orchestrator code only, never a model | Install and update apps, reload, oneshot into `pw_*` |
| `parsewright_drift` | Drift collector code only | Read-only, role search filter limited to registered sourcetypes |

The exact capabilities for app install and reload on the deploy role are confirmed in the lab on day 1.

### Deferred

Per-resource authorization and approver ≠ submitter (multi-team use), upload rate limits, TLS verification and token rotation (the lab uses self-signed certificates), data retention policy (samples kept while the TA exists; uploads deleted after the job), PostgreSQL backups.

**Demo angle:** "What if an attacker controls the logs your AI reads?" Show an injected instruction in a log line and the gate blocking it, and the agent's attempt to set `action` to a constant being caught.

## Build details

Plain Python, no agent framework: the flow is fixed and small, and readable code is easier to debug under deadline and easier for judges to review.

### Tech stack

| Layer | Choice |
| --- | --- |
| LLM client | `openai` SDK, `base_url=https://api.meta.ai/v1`, model `muse-spark-1.3` (env vars `LLM_BASE_URL`, `LLM_MODEL`) |
| Schemas | `pydantic` |
| Backend | FastAPI |
| Splunk | `splunk-sdk` over REST :8089, token auth |
| Ledger | PostgreSQL: job queue and ledger, written on every state transition |
| UI | Next.js + shadcn/ui, live updates over server-sent events from FastAPI |
| Lab | Splunk Enterprise standalone VM on Proxmox |
| Judges | `docker-compose.yml` with the official Splunk Enterprise image + the app |

### Platform and UI

Decision: a Python engine behind FastAPI, with a Next.js UI. The engine runs headless first (`parsewright run samples.log`); the UI is added once the loop works end to end.

The UI only reads the ledger and sends two actions (confirm profile, approve or reject); it holds no logic. FastAPI streams ledger events to the browser as they happen.

| Screen | Shows | Actions |
| --- | --- | --- |
| New run | Upload or drop folder, board of all jobs and states | Start run |
| Live run view | State stepper, attempt timeline with config diffs, check results and evidence, agent searches | None (watch) |
| Profile review | Editable Log Profile: vendor, timezone, categories, CIM targets | Confirm |
| Approval report | Raw vs parsed events with highlights, mapping table, CIM scores, iterations per stage, final configs | Approve, reject, correct a mapping, download `.tgz` |

Budget about 2 days for the UI. Fallback if the engine runs late: a one-day Streamlit UI.

Stretch goal: send ledger events to a `pw_audit` index with a small Splunk dashboard, so SOC teams can monitor agent activity in Splunk.

Note: Splunk uses PCRE, which neither Python `re` nor JavaScript `RegExp` matches exactly; `test_regex` uses the Python `regex` package as a closer match, and the Validator inside Splunk stays the real proof.

### Repo structure

Layout note (Phase 0): the Python modules below live in the installable package `engine/parsewright/`, and `ui/` is `web/`; `docker-compose.yml` stays at the repo root.

```
parsewright/
├── api/              FastAPI routes (upload, runs, approve)
├── orchestrator/     state machine, budgets, routing
├── agents/           profiler, index_time, extraction, cim_mapper (prompt + schema each)
├── tools/            splunk client, search guard, regex test
├── guardrails/       conf key allowlist, post-install warning check, regex safety
├── validator/        fixed checks per stage
├── ta_builder/       writes TA files, versions, packages .tgz
├── ledger/           PostgreSQL models (jobs, ledger)
├── cim_spec/         required fields + allowed values per model
├── generator/        synthetic logs + truth manifests
├── ui/
└── docker-compose.yml
```

### Hackathon compliance checklist

- [ ] Claim the $150 Meta Model API credits (card on file, spend limit set)
- [ ] Fresh public repo, first commit on Oct 27; all code written Oct 27 to Nov 4
- [ ] Only synthetic or self-generated logs; no client data anywhere
- [ ] Meta models do the core reasoning (Stage 1 pass/fail)
- [ ] 3-minute demo video showing only hackathon-built features
- [ ] Submit by Nov 4, 9:00 PM ET (Thu Nov 5, 05:00 Qatar time)
- [ ] Check the full judging rubric on the live guide page

### Open questions

Phase 1 tracks these, plus five questions about the REST deploy, ingest and config-check paths, with test steps and results in [lab-findings.md](lab-findings.md). Answers are recorded here as they land.

- Does the Meta Model API support `response_format` JSON schemas, or should each agent output be a forced tool call? *(2026-10-27: answered. `response_format` with a strict JSON schema works and is the mode every agent uses. The model reasons before answering, so output caps must leave room for it. See [lab-findings.md](lab-findings.md#q1-structured-output-from-the-meta-model-api), Q1.)*
- What exactly is "contributor mode"? Default to standard mode until confirmed. *(2026-10-27: answered. On the Meta Model API it means calling a model's contributor-mode variant: discounted usage, but Meta may train on the content, and confidential data is not allowed. Parsewright uses standard mode; a variant is allowed only for synthetic-only dev runs. See [lab-findings.md](lab-findings.md), Q2.)*
- Do index-time settings apply to the next oneshot right after a reload on the lab's Splunk version? *(2026-10-27: answered for a new sourcetype. They apply to the next `receivers/simple` ingest right after install, with no reload. See [lab-findings.md](lab-findings.md), Q3.)*
- Edge cases in scope: multiple event types per file, multi-line events, missing timezone, epoch timestamps, CSV headers (`INDEXED_EXTRACTIONS`)? *(2026-10-27: decided. In: multiple event types, missing timezone, epoch timestamps. Stretch: multi-line. Out: CSV `INDEXED_EXTRACTIONS`; CSV stays supported at search time. See [lab-findings.md](lab-findings.md), Q4.)*
- Four agents, or merge Extraction and CIM mapper into three? *(2026-10-27: decided. Keep four, for focused context, single-owner failure routing, and no CIM gaming through extractions. Merging is the fallback only if Phase 3 runs late. See [lab-findings.md](lab-findings.md), Q5.)*
