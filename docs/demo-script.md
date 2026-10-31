# Demo script (3 minutes)

The video shows only features built during the hackathon (Oct 27 – Nov 4, 2026), all on synthetic Acme logs. Each moment is a repeatable script in [demo/](../demo/); runs that take minutes are started before recording and shown when they reach the interesting state.

## Before recording

1. Stack up (`make up`, or the lab with `parsewright serve --workers 4` and the web UI), the browser on http://localhost:3000, and a second tab on Splunk Web.
2. Check the API credit balance. The pre-runs below use about 550–700k tokens in total.
3. Pre-run, in this order, and note each printed job id:

   | Script | Leaves behind | Tokens |
   | --- | --- | --- |
   | `demo/03_guardrail_block.sh` | the injected-log run, with the blocked proposal and the caught constant | ~100k |
   | `demo/05_approval_report.sh` | a run awaiting approval with the `<script>` log line | ~100k |
   | `demo/06_parser_update.sh` | a parser update awaiting approval (needs `TA-parsewright-acme-fwdemo` promoted at 1.0.0) | ~30k |

4. Start the live ones during the take: `demo/04_parallel_jobs.sh` (4 jobs, ~250–400k tokens) right before 0:20, and keep `demo/07_live_workspace.sh` ready as a fallback for the live view.

## The take

| Time | Show | Say |
| --- | --- | --- |
| 0:00–0:20 | The runs board, empty, then "New run". | "Every new log source in a SOC needs a Splunk parser. Line breaking, timestamps, fields, CIM: hours by hand per source, and an index-time mistake corrupts data forever. Parsewright writes the parser and proves it works in Splunk." |
| 0:20–0:45 | `demo/04_parallel_jobs.sh` starts: four rows appear, each with the agent at work. One pins itself under "Needs you". | "Four sources at once. Muse Spark agents do the reasoning, one per stage. This one waits for me to check the profile; the others keep going." Confirm the profile: it resumes. |
| 0:45–1:15 | Open a running job: the Now banner, the phase rail. Click Extraction, attempt 1: a failed check with expected vs actual and the failing event. Attempt 2: the diff rows, then "Passed". | "Agents propose, code acts, Splunk judges. Attempt 1 missed a field; Splunk said exactly which events. The agent got that evidence, and attempt 2 changed one setting and added one. Splunk passed it, not the model." |
| 1:15–1:45 | The injected-log run (`03`): the log line with the injected instruction; in the CIM phase, the guardrail gate's block with its reason; then the Validator catching the constant `action`. | "What if an attacker controls the logs the AI reads? This line tells the model to map every event as a success. The gate blocks it before Splunk ever sees it. A subtler trick, a constant value, passes the gate, and the Validator catches it, because it compares every event with the truth." |
| 1:45–2:25 | The approval report (`05`): CIM meters and attempts per phase; raw vs parsed, hovering a field to light it on both sides; the `<script>` line as plain text; the CIM view; the configuration as the .conf files. Approve: the SHA-256 and the second confirmation. Download the `.tgz`. | "Every field has one colour in the raw line and the parsed event. This line carries a script tag: it is just text. The approval is bound to the exact package's hash, and the add-on is installed under its real name with a smoke test." |
| 2:25–2:50 | The parser update (`06`): Diagnose (no AI), only the failing stages patched, the diff against production as rows, the rollback command. | "When the device firmware changes the log format, Parsewright finds what broke without a model call, patches only that, and proves the old format still parses." |
| 2:50–3:00 | The board, all jobs done or awaiting approval. | "Parsewright: agents propose, code acts, Splunk judges, you approve. On Muse Spark, or on-prem with Muse Spark Open so logs never leave your network." |

## If something fails during the take

- A live job is slow: cut to a pre-run job at the same phase; the workspace looks the same.
- The model gets a stage right first time (no fix loop to show): open `03` or `07`'s earlier job, which has one, via its phase link (`/runs/<job>?phase=extraction&attempt=1`).
- Nothing is promoted on approve: the smoke test result is in the Promoted phase; show it, then move on.
