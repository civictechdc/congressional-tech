---
id: ct-0jgy
status: open
deps: []
links: [ct-x00f, ct-01kq]
created: 2026-11-10T17:00:46Z
type: task
priority: 1
assignee: mikewolfd
tags: [engine, memory, measurement]
---
# Run recorder: lowest shared-budget available, copies, refusals, pool peak and real memory per step, and a two-run comparison

W9 of the docspec-rs feedback refactor (.cache/archive-release/investigations/docspec-feedback-20261110/root-cause/PLAN.md, section 'The prefix run'). The qualification of the next engine pin (ct-x00f) has a pass condition no existing tool reports: the lowest shared-budget 'available' per step, because pool_reserved_peak counts only the native pool and cannot show charge moving into the half of the budget that cannot spill. One script, extending scripts/measure/step_memory.py (ct-01kq), reads three files a run already produces (the engine's stderr with RUST_LOG=docspec=info,docspec::budget=debug, the step log, the watchdog timeline) and prints per step: lowest shared-budget available (minimum over the 'shared admission request' lines attributed to the next statement event in the same stream; note the logged value is the amount available BEFORE that acquisition), copies (those lines whose caller is the view-compaction reserve), refusals, pool_reserved_peak where the binary logs it, peak RSS and physical footprint, seconds; and compares two runs step by step. Developed against a real debug log made locally with the pinned binary on the M1 job. Approved by the coordinator 2026-11-10 because ct-x00f depends on it.

## Acceptance Criteria

On a local run of the pinned binary with the debug log on, the per-step table agrees with a hand count on three steps; a planted wrong value (a debug line moved to the neighbouring statement, an 'available' read after instead of before the acquisition) fails a test; the two-run comparison lists the steps whose floor, copies or memory moved; unreadable input is refused with exit 2, not a traceback; focused tests through the project runner; independent review; one full lane or all six shards.


## Notes

**2026-11-10T17:12:34Z**

2026-11-10: also to fix here, from the review of ct-01kq (same script): refuse with exit 2 a timeline sample whose epoch or read_seconds is null or not a number (step_memory.py:81,128 give a TypeError traceback today); refuse two runs concatenated in one timeline (epoch minus seconds is constant within a run).
