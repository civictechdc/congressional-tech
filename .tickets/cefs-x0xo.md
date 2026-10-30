---
id: cefs-x0xo
status: closed
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

**2026-10-28T07:11:41Z**

ONE bounded five-parent native projection succeeded39.663s/5rows/30179B after explicitCOREEND; resource window immediately freed. Immutable shared/e4-five-parent-ca064ca9 retains result/pins/nested records. All five query URLs are ?download=1 children of no-query download parents with source_record receipt pointers; second occurrences are inherited linked_ancestor context, not independent raw link proof. Exact House-pages parent receipt keys/lines sent to raw+engine. No raw bodies, extractor, broad comparison or tests run. E4 remains incomplete5members with null field/cause/unexplained counts; no invented fetch, alias rule or derived-only classification. See docs/measurements/engine-first-20261027/site/e4-five-parents.md.

**2026-10-30T14:32:57Z**

Completed E4 full-corpus parity verification (docs/measurements/engine-first-20261027/e4/full-raw-e2-parity-20261030.json, 0 unexplained differences).
