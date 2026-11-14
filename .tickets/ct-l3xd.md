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

Direct source review of pilot dbaa560cf220b77d9ea839faaf6485675a5e38b92f2d6fa31c6068a48a20ceab pages 600 and 1100 found substantial omissions already present in page checkpoints. Two exact three-band replays showed one recognized line on each page is discarded by the 11-pixel edge rule despite having no overlapping retained detection. Other missing prose was never emitted by Vision and is a separate cause.

## Design

Fix the maintained SpicyDocs strip merger narrowly. Preserve unique edge detections while using the existing line-overlap comparator to suppress duplicate clipped copies. Keep the active CT OCR lane and all original checkpoints unchanged. New outputs require a separately declared candidate identity, then named raw/intermediate/final review. Alternate one/four-band candidates have gains and losses and are not approved replacements.

## Acceptance Criteria

Show the old code fails unique-edge cases and retains duplicate controls; pass maintained focused/native Vision checks; replay only the two named pages and reuse unchanged cached pages; use GPT-6.1-Terra medium for an independent raw-page -> detections -> final-text comparison; qualify shared release and CT version/selection separately. Do not claim to repair text Vision never detected.


## Notes

**2026-11-14T16:03:03Z**

Shared candidate committed at 7957a02634c809e35bcecac1151e6a854c971985. Four new unique-edge cases fail old source; two duplicate controls pass; repaired Apple Vision focus passes all 14 cases. Real two-page replay used 0.426 GiB RSS / 1.9 seconds and preserves all 76/47 baseline detections, adding one previously dropped line on each page. Terra medium independently read both raw pages, actual detection/merge records and final text, accepting improved term availability. Page 1100 adds its line out of source order, so phrase order remains a known gap; both pages still omit prose Vision never detected. Independent code review follows; shared release and CT policy qualification remain separate. Evidence: repairs/ocr-checkpoint-resume-20261114/page-gap-diagnosis-20261114/unique-edge-fix/.
