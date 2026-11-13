---
id: ct-cbkz
status: in_progress
deps: [ct-55qo]
links: [ct-chc4, ct-m704, ct-f6hr]
created: 2026-11-12T15:38:26Z
type: task
priority: 2
assignee: mikewolfd
external-ref: ss-mkxe
tags: [congress_api, body_text, spicy-docs, html, xml, post-wave-6]
---
# Adopt qualified spicy-docs markup normalization and reparse the non-OCR cohort

The independent audit found upstream normalization commits 847a32fd and e247fc9b already implemented in spicy-docs but absent from CT's pinned GPO wheel. Credit that work; inspect and qualify the remaining contextual <pre> and adjacent-link spacing gaps before packaging. The old claim that all PDF output was clean and the CPU reread would take minutes is withdrawn.

## Design

This ticket owns the single composed spicy-docs wheel for CT: retain the merged GPO cleanup, adopt qualified markup changes, and coordinate Tesseract identity support with ct-n3ik. Reuse shared markup walkers rather than adding a CT parser. ct-f6hr owns encoding, XML subset and event-limit compatibility. ct-55qo owns selected reading keys; compaction cannot substitute for selection. Keep historical readings and refusal evidence until exact retained-table reconciliation passes.

The retained inventory names 310,964 unique HTML/XML bodies (310,047 completed baseline plus 917 recovery targets), with 11.92 GB of existing text. Measure a bounded CPU pilot and estimate full input/output/scratch cost before reprocessing. WARC is excluded from the ordinary cohort deliberately: establish payload and saved-body reachability before adding it. No PDF OCR rerun; OCR remains paused.

## Acceptance Criteria

1. The composed wheel passes real bill XML, mixed HTML with local <pre>, adjacent links/buttons and GPO verbatim controls. PDF text and declared PDF identity remain unchanged relative to the chosen baseline.
2. A measured CPU-only pilot and complete deduplicated HTML/XML manifest name supported, malformed, refused and unassessed bodies; no PDF enters that lane.
3. Reparse the qualified non-OCR cohort with measured capacity and compare text, refused and pending records in both directions. WARC requires a separate justified reachable cohort.
4. Publish only ct-55qo selections; retain earlier evidence and prove row uniqueness before any separately authorized destructive compaction.

## Notes

**2026-11-13T17:46:16Z**

2026-11-13 reconciliation: retain this ticket's CPU markup-normalization scope with upstream ss-mkxe. New compatibility work (legacy HTML encodings, empty XML internal subsets and max_events) is tracked separately in ct-f6hr. The earlier statement that PDF text was clean was limited to that sample and is superseded by source-confirmed GPO loss: PR #151 fixed cleanup, and ct-kfsd owns its historical reread/publication. For this markup-only change, preserve PDF output relative to the chosen current baseline; do not restore an obsolete PDF pin. Before compaction, retain replayable prior readings/refusals and verify one current selection per body/parser. Verify current shared-reader implementation and qualification before duplicating it.

**2026-11-13T18:48:44Z**

Rewritten from the independent ETL/greybeard/evolutionary audit. Prior notes and evidence remain below; old running-job and automatic reread assumptions are superseded. Audit: .cache/archive-release/ocr-recovery-20261113/coordination/greybeard-root-cause-20261113/review.md; cohort and page inventory: inventory/README.md.

**2026-11-13T19:34:05Z**

Packaged the qualified markup slice from spicy-docs ce38a3db87438f247262fe9485fda5efaa95e3a6 as 0.85.0+markup.20261113 (wheel SHA-256 3b8fd70132cee1f3c64aaefa251fcec3fff9b22d1eb323d1242c06778dc6ae56). Reuses 847a32fd/e247fc9b while retaining GPO cleanup. Independent review caught and fixed generic-XML field concatenation/metadata loss, namespace alias/rebinding errors, hidden pre state and cross-event spaces. Only the Congressional native bill DTD or GPO USLM namespace qualify legislative metadata/inline rules; other XML and unknown/foreign fields retain boundaries. Raw evidence spans remain literal. Two builds are byte-identical and every wheel RECORD/source member verifies. Shared focused suite: 326 passed, 3 skipped, 2 deselected. CT focused suite: 73 passed (partial lane), watchdog peak 0.85 GiB RSS. Seven retained actual-CT native-only consumer cases cover six markup bodies and one native PDF: GPO pre controls and PDF text/offsets/cleanup unchanged; all four HTML bodies conserve non-whitespace text. HTML/XML and composed WARC receive explicit new declarations; PDF identity remains 4d04558965d9baf630033c94857169bfddad68988fce34041a4a35a0c6ddd2a8. Evidence: .cache/archive-release/ocr-recovery-20261113/repairs/ct-markup-readers-20261113/. This small local sample is not a corpus throughput estimate. Keep this ticket in progress for representative/largest-input pilot, source reachability and the 310,964-body reparse/qualified-selection acceptance. ct-f6hr compatibility remains separate. OCR paused; publisher refetch deferred.
