# demo

Repeatable scripts for the moments shown in the 3-minute demo video. Each "RECORD THIS" note in a phase summary (see CLAUDE.md, "Build log and demo moments") gets a script here. That way the moment can be re-run and recorded at any time, not only on the day it first worked.

## Conventions

- One script per moment, numbered in demo order: `NN_short_name.sh`, for example `01_fix_loop.sh`.
- Each script:
  - uses only synthetic fixtures from `engine/parsewright/generator/fixtures/`;
  - reads all configuration from `.env`;
  - never prints tokens or keys.
- Scripts write only to `pw_` test indexes and `__test_<job>` apps, like the rest of Parsewright, and clean up what they create.
- The top of each script states what it shows, its prerequisites (lab running, tokens set) and roughly how long it takes.

## Moments

| Script | Moment | Phase | Status |
| --- | --- | --- | --- |
| `01_fix_loop.sh` | First agent fix loop: TZ = UTC is caught as a +32400 s offset, attempt 2 sets Asia/Tokyo and passes | 2 | Recorded in the lab, Oct 27 |
| `02_cim_green.sh [vpn\|fw\|ssh\|proxy]` | First green CIM check: all three stages, the holdout line and the three CIM numbers | 3 | All four fixtures green in the lab, Oct 28 |
| `03_guardrail_block.sh` | Prompt-injection log; a simulated compromised model's CIM proposal blocked by the gate, a subtler constant caught by the Validator, then the real model recovers | 4 | Recorded in the lab, Oct 28 (the real model ignored the injection; the attacker proposals are simulated and labelled) |

The likely moments for the remaining phases are marked "RECORD THIS (likely)" in [docs/build-plan.md](../docs/build-plan.md). They are added to this table when the phase produces them.
