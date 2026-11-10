---
id: ct-6p6d
status: open
deps: []
links: [ct-64t4, ct-w2kf, ct-07wr]
created: 2026-11-10T13:27:30Z
type: task
priority: 2
assignee: mikewolfd
tags: [nightly, performance]
---
# Nightly wall time: 27 minutes measured, and the cuts not yet made

Owner asked 2026-11-10 why the nightly takes so long. Measured from steps.jsonl of the build 04:39Z (shell-started, 25 min) and the scheduled run 12:15Z (26.7 min, 1,832 engine steps, 1,241 step-seconds): setup about 1 min; daily read about 12 min; model 11.4 min in one 301-step engine job, no step over a minute (entity_profile_completeness 41 s, url_state_lines 31 s, pinned_readings 26 s); gate under a minute. Already fixed: the launch agent ran as a Background process at priority 4 on efficiency cores (46 min; ct-xnn6). Not yet cut: (1) the daily runs the same full scan in three producer passes (pending_bodies 47-62 s, settled_parsers 20 s, admission checks 13 s each time) and current_page_readings twice at 30 s: about 2.5 to 3.5 min repeated; (2) the model is a full rebuild whenever its identity changes, and uv.lock is in the identity, so a dependency bump with no model effect costs 11 min; (3) the engine is limited to 2 threads on a 14-core Mac (congress-1 is measuring 2, 4, 8 on the 147-step prefix); (4) an incremental model that rebuilds only what changed is a project, not a fix.

## Acceptance Criteria

The repeated daily scans run once per night, or the reason they cannot is written here. The thread measurement is recorded with a decision. Each remaining item is done, declined with a reason, or split into its own ticket.


## Notes

**2026-11-10T13:39:21Z**

2026-11-10 thread measurement (congress-1; .cache/archive-release/investigations/thread-measure-20261110/RESULT.md; 147-step prefix to base_normalized, pinned engine b0342a73, one run each, OCR at 8 workers alongside): 2 threads 444.1 s / 7.83 GiB, 4 threads 405.7 s / 7.94 GiB, 8 threads 423.0 s / 7.41 GiB, exports byte-identical. Item 3 is answered: engine threads are not the limit (4 is 9% faster than 2, 8 is slower than 4). Slowest steps are the same at every count: pinned_readings 29-32 s, link_inputs 17-20 s, appearance_url_inputs 18-20 s, placeholders 16 s. Unprofiled candidates: step results reach later queries through a one-partition streaming table, remote lake reads, single-threaded operators. Next cheap step if the model is to be faster: a sampling profile of pinned_readings and link_inputs.

**2026-11-10T15:47:02Z**

2026-11-10 root-cause analysis, measured (root-cause/ROOT-CAUSE.md cause A; PLAN.md M1). Where the model's time goes in build c03c43da (902 s): 44 of 336 statements read a lake table and take 545 s (61%); captures is scanned 42 to 46 times and readings 50 to 70 times per build (the selected_readings view holds 11 scans of readings and is used 6 times). At 2, 4 and 8 threads those statements took 254, 251 and 255 s while statements over step results took 177, 138 and 152 s: the lake scan ignores compute_threads (iceberg-datafusion 0.10.1 exposes one output stream; its file concurrency is the CPU count). Measurement M1: the 11 statements that read only captures take 144.9 s in that build and 9.2, 7.4 and 6.8 s on a local copy of the table at 1, 2 and 8 threads, same pinned binary. So the cost is the remote read path, not threads and not decoding. Fix being built in docspec-rs: read each lake file once (a read-through cache for immutable lake objects). The daily's repeated scans in item 1 are the same cause. Item 3 (threads) is answered: do not raise them for speed.

**2026-11-10T20:39:29Z**

2026-11-10 one more figure: the fresh release-night run (nightly/20261110T195322.097664Z, d3ed7ca5) took 1,658.6 s in its publish step (model, export and gate). The captures read-once change (ct-07wr) did not ship in this release; it moved to the next one.
