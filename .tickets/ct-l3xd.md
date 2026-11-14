---
id: ct-l3xd
status: in_progress
deps: []
links: [ct-aitp, ct-t4p3, ct-a73a, ct-n3ik]
created: 2026-11-14T15:56:14Z
type: bug
priority: 1
assignee: mikewolfd
tags: [source_quality, body_text, followup]
---
# Preserve unique OCR detections at strip boundaries

The shared strip-edge fix is merged in SpicyDocs PR #31 at 19869b0ca0738869f39743a076daa637cf6a362d after CI and independent review. It retains recognized unique edge lines while avoiding nonadjacent duplicate retention. Direct two-page review accepts improved search-term availability, with remaining missing prose and reading-order limits. CT wheel/policy composition and selective page adoption remain; the active OCR run keeps its frozen version.

## Design

Fix the maintained SpicyDocs strip merger narrowly. Preserve unique edge detections while using the existing line-overlap comparator to suppress duplicate clipped copies. Keep the active CT OCR lane and all original checkpoints unchanged. New outputs require a separately declared candidate identity, then named raw/intermediate/final review. Alternate one/four-band candidates have gains and losses and are not approved replacements.

## Acceptance Criteria

Show the old code fails unique-edge cases and retains duplicate controls; pass maintained focused/native Vision checks; replay only the two named pages and reuse unchanged cached pages; use GPT-6.1-Terra medium for an independent raw-page -> detections -> final-text comparison; qualify shared release and CT version/selection separately. Do not claim to repair text Vision never detected.


## Notes

**2026-11-14T16:03:03Z**

Shared candidate committed at 7957a02634c809e35bcecac1151e6a854c971985. Four new unique-edge cases fail old source; two duplicate controls pass; repaired Apple Vision focus passes all 14 cases. Real two-page replay used 0.426 GiB RSS / 1.9 seconds and preserves all 76/47 baseline detections, adding one previously dropped line on each page. Terra medium independently read both raw pages, actual detection/merge records and final text, accepting improved term availability. Page 1100 adds its line out of source order, so phrase order remains a known gap; both pages still omit prose Vision never detected. Independent code review follows; shared release and CT policy qualification remain separate. Evidence: repairs/ocr-checkpoint-resume-20261114/page-gap-diagnosis-20261114/unique-edge-fix/.

**2026-11-14T16:48:29Z**

Final shared head 0f1311d6b9ab7a551ec612619dc12eebcb580989 passed the planted 50-band nonadjacent duplicate case and independent code review. Terra medium directly read original pages600/1100, actual recognizer records, checkpoint and final text: one source line restored on each, no completeness claim; p1100 inserted line order remains imperfect. Twelve nonnative controls plus one native leak test passed (the latter made 70 synthetic-PDF recognition calls, not corpus re-OCR). Exact reports/hashes under ocr-checkpoint-resume-20261114/page-gap-diagnosis-20261114/unique-edge-fix/. Next compose a distinct CT policy in an inactive checkout, qualify selected-page output, and preserve active 09fd OCR bytes.
