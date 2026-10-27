---
id: cef-c9e8
status: in_progress
deps: []
links: []
created: 2026-10-27T04:54:00Z
type: task
priority: 2
assignee: mikewolfd
tags: [engine-first, S1, E1]
---
# S1/E1: specify executable document fixtures and registry seeds before model SQL

## Acceptance Criteria

Every S1 fixture has explicit inputs and expected results before SQL; all formats and registry samples are covered; real slices execute with the draft rules; main-content extractor is chosen on paired captures with measured time.


## Notes

**2026-10-27T07:27:05Z**

Page contracts precede binding: literal/order/group/date/namespace/entity/fingerprint cases. Current page-reader checks:89 pass, including15 new contracts. Trafilatura2.0.0 on3425 locally located bodies gives3424 nonempty and1622 equal candidate endpoint groups; readability0.9 gives3291/1562. Full discovery6470 candidate bodies;3045 remain unavailable locally after412529-file metadata inventory. S1 stays open: sniff, registries, semantic SQL, real slices, full qualification and labeled sample. See docs/measurements/engine-first-20261027/s1-pages.md; no live storage access or writes.
