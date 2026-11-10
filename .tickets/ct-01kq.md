---
id: ct-01kq
status: in_progress
deps: []
links: [ct-64t4, ct-psb5, ct-0jgy]
created: 2026-11-10T15:46:33Z
type: task
priority: 2
assignee: mikewolfd
tags: [watchdog, memory, observability]
---
# Real memory per statement from the watchdog timeline and the step log

From the docspec-rs feedback root-cause analysis (cause D, pipeline half). The engine's pool figures are a ledger, not memory: build c03c43da's real peak (10.28 GiB physical) came during the export of member_votes.parquet while the pool showed 2.81 GiB. The watchdog timeline and the step log already hold what is needed; they lack a shared clock and a join. Change: each timeline sample carries the wall-clock epoch; scripts/measure/step_memory.py joins a step log with a timeline and prints peak footprint per statement and the --expect-gb to use. Branch claude/dx-step-memory. Links ct-64t4, ct-6p6d.

## Acceptance Criteria

The script reproduces the report's figures on build c03c43da (run peak 10.28 GiB during the member_votes.parquet export at 2.81 GiB pool); a timeline without epoch needs an explicit offset; no reader of timeline files breaks; lane and independent review done.


## Notes

**2026-11-10T17:00:46Z**

2026-11-10: built and independently reviewed (no must-fix); both review fixes are in (f7d1f75f, 7966a28d, ddaf7fb8 on claude/dx-step-memory): the report says which statement the highest reading FELL IN, and names the statements it overlaps when none spans it; bad input is refused with exit 2 or reported, never a traceback. 61 focused tests pass (partial); 21 planted wrong values each fail a test. Outstanding: the reviewer's confirmation of the fixes and one full lane. While this was built a hung watchdog was found: ct-psb5.

**2026-11-10T17:12:34Z**

2026-11-10: the reviewer confirmed both review fixes at ddaf7fb8: no must-fix, the three verdicts stand (ship), ready for its full lane (which waits for the release's lanes and build). Two small notes go to the run recorder (ct-0jgy), which edits the same script: a timeline sample whose epoch or read_seconds is null or a string still gives a TypeError traceback (scripts/measure/step_memory.py:81,128; the watchdog cannot write that today); two timelines concatenated at a line boundary are read as one run (a constant epoch-minus-seconds check would catch it).
