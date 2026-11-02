# validator

Fixed SPL checks per stage (index-time, extraction, CIM), run through the Splunk SDK. Code only, no AI; it alone moves a run forward.

Status: built: `index_time.py`, `extraction.py`, `cim.py` (three-number CIM score), and `mechanical.py`, the checks for a log without a truth manifest: each `_time` equal to the time read by code from its own raw line, a human-stated zone when timestamps carry none, values exactly as written in their line, CIM anti-gaming, and, for parser updates, exact equality with production's own output. See [docs/design.md](../../../docs/design.md), section "Validation design".
