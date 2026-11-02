---
id: ct-ud0b
status: open
deps: []
links: [ct-4jms, ct-tk10]
created: 2026-11-02T13:59:14Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, gates, daily, phase2]
---
# Publish nightly when every change is a new row traced to new receipts

Owner decision 2026-11-02: after the fixed release, publish nightly without a person when every difference from the live release is an addition traceable to receipts newer than the live release, checked against the raw receipts (provenance), not by trusted change types. Any changed or removed existing value stops the publish and waits for a reviewed cause record (gate 1). Pulled forward from Round 4. Known limit: a bug that only adds wrong rows can still pass; the other gates (links, required fields, producer proof, end-to-end) still run.

## Acceptance Criteria

- Gate 1 records an automatic cause for an addition-only difference group only when every added row's source receipts post-date the live release's input record, verified by reading the receipt keys and dates, not the model.
- Any changed or removed existing value refuses as today.
- Tests: additions from new receipts pass; an added row from an old receipt refuses; a changed value refuses; a removed row refuses.
- The daily workflow (archive-jobs publish after capture) runs this unattended; the pointer flips only when all gates pass.

