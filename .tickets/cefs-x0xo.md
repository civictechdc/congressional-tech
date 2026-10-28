---
id: cefs-x0xo
status: in_progress
deps: []
links: []
created: 2026-10-28T00:01:03Z
type: task
priority: 1
assignee: site
---
# E4 pinned-catalog parity by source evidence and cause

Owner run4: native SQL many-to-many comparison against exact pinned documents/filenames catalog pair, actual browser-visible candidate fields, cause predicates/counts/examples and unexplained classification. F0 testcandidate only; E2firstrelease pending engine.

## Acceptance Criteria

Expected fixture and native tests bind evidence alignment, IDs, each known cause, unexplained rows and owner blockers; full F0 run shows only demonstrated conversion gaps; real E2 parity runs when first candidate exists.


## Notes

**2026-10-28T04:34:52Z**

Native parity comparison and focused fixtures implemented through 506f8ecf; final combined E4/workflow/gate lane 65 passed on ordinary engine-9b59263. CODE reviews approved after forward fixes. Actual model slice ac866cc3 passed reader/canary and desktop/phone browser checks. Actual E4 invoked and refused current_recoveries missing agreed body_sha256/recovered_url/decided_at/identity_note aliases before SQL. Blocked: engine must publish corrected immutable evidence plus descriptor/profile pins, then run DOCSPEC_JOB_CONFIG=$COORD/shared/engine-9b59263/runtime.json .venv/bin/python -I scripts/measure/archive_parity.py compare --inputs <engine-descriptor> --work <fresh-owned-directory>. Full F0 comparison not qualified (2 GiB scratch cap); owner stopped full F0 runs for the real vertical slice. Ticket remains open; no full parity or cause counts claimed.

**2026-10-28T05:43:27Z**

Corrected immutable 167c6a78 passes pins/profile/layout. Query-shape fix 67ad584b removes a single-use materialization and uses small build inputs, with unchanged budgets and 42 E4 tests passing. Actual scope completes 20.573s/3251617792B peak tree RSS: 50 old docs/55 files, five partial components/five missing sources. Guard returns incomplete with null field/cause/unexplained counts; no field comparison ran. Immutable shared/e4-slice-67ad584b includes exact five scope gaps and native proof. Engine requested raw to extend those sources without changing old membership.
