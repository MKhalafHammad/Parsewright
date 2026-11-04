# Demo script (3 minutes)

The video shows only features built during the hackathon (Oct 26 – Nov 4, 2026), all on synthetic Acme logs, in the real web UI against the lab Splunk. Every moment has a repeatable script in [demo/](../demo/README.md). Runs that take minutes are run beforehand and opened when they are in the state to show; two fresh uploads run live during the take.

The recorded take is 2:50, 1920×1080, with on-screen captions. The "Say" column is the matching narration for a voice-over.

## Before recording

1. The engine and the UI running (`make up`, or `parsewright serve` and the web UI in the lab), the browser on http://localhost:3000.
2. These runs exist. The script that reproduces each one:

   | Scene | Reproduced by | State it must be in |
   | --- | --- | --- |
   | Fix loop | `demo/01_fix_loop.sh` | Index-time attempt 1 failed by 32400 s, attempt 2 passed |
   | Guardrail gate | `demo/03_guardrail_block.sh` (the take shows a real block from a `demo/04_parallel_jobs.sh` run) | a proposal blocked by the gate, with its reason |
   | Injected log | `demo/05_approval_report.sh` | awaiting approval, with the `<script>` log line |
   | Just the log | `demo/08_log_only.sh` | awaiting approval, with the decisions section |
   | Timezone | `demo/08_log_only.sh timezone` | paused in profile review, asking for the zone |
   | Parser update | `demo/06_parser_update.sh`, then `diagnose` | the update with a rejected attempt; a second update that stopped at Diagnose with 0 tokens |

3. Two fresh synthetic logs ready to upload live (about 50k tokens each).

## The take

| Time (about) | Show | Say |
| --- | --- | --- |
| 0:00–0:17 | Title card; the runs board; the "New run" sheet. | "Every new log source needs a Splunk parser. By hand, that is hours of props.conf per source. Here you upload only the raw log." |
| 0:17–0:30 | Two logs uploaded; both rows run in parallel; one run's workspace with the agent at work. | "Two logs at once, each a job, run in parallel. Muse Spark agents do the work, one per stage: Profiler, Index-time, Extraction, CIM mapping." |
| 0:30–0:50 | The fix-loop run: Index-time attempt 1, Splunk's check with every timestamp 9 hours off; attempt 2. | "Every proposal is deployed to a real Splunk and checked on every event. Attempt 1 guessed UTC: all 60 timestamps 9 hours off. The evidence goes back; attempt 2 sets Asia/Tokyo, and Splunk passes it." |
| 0:50–1:08 | The guardrail gate's block with its reason; the injected log line and the `<script>` tag in raw vs parsed. | "A guardrail gate refuses anything off its allowlist before it reaches Splunk, and tells the agent why. Logs are data, never instructions: an injected prompt and a script tag are shown as plain text." |
| 1:08–1:45 | The log-only run: how it was validated; the decisions (`accept → allowed` ×161, `drop → blocked` ×79); raw vs parsed; the Approve dialog with the SHA-256, then cancel. | "No answer key for this log, and it is still checked on every event: times read from each line, every value exactly as written. Meaning cannot be proven by code, so the agents' decisions are listed. A human approves exactly this package, by its SHA-256." |
| 1:45–1:53 | The paused run asking for the timezone. | "No timezone in the timestamps? The run asks a human instead of guessing." |
| 1:53–2:38 | The parser update: Diagnose; the CIM attempt rejected for breaking the old format; the changes against production; the update that stopped at Diagnose with 0 tokens; the TA registry. | "New firmware, new log format. Diagnose re-tests production on the new samples, with no AI, and finds what broke. Only broken stages are patched. This attempt broke the old format, so it was rejected; attempt 2 parsed both. The change is applied in place, keeping admins' local settings, with an exact-version rollback. If nothing broke, it stops at Diagnose: zero tokens. Every promoted add-on is registered with all its versions." |
| 2:38–2:50 | The board, the live jobs further along; the closing card. | "Agents propose, code acts, Splunk judges, you approve. Parsewright, built with Meta Muse Spark." |

## If something fails during the take

- A live job is slow: the board still shows it running; the scenes after it use runs made beforehand.
- The model gets a stage right first time (no fix loop to show): open an earlier run that has one by its phase link (`/runs/<job>?phase=index-time&attempt=1`).
- Approving is not part of the take: the dialog is opened to show the SHA-256, then cancelled, so no add-on is promoted by the recording.
