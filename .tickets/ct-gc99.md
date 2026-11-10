---
id: ct-gc99
status: in_progress
deps: []
links: []
created: 2026-11-10T03:26:30Z
type: task
priority: 2
assignee: mikewolfd
tags: [gate, release]
---
# Release gate's automatic cause cannot cover a backlog ingest

AUTOMATIC_GROUPS accepts an addition only when it traces to receipts newer than the live release's newest dated receipt. On 2026-11-10, 565 of the 727 added documents came from receipts new to the release but dated 2026-10-31, older than that mark, so the automatic proof refused at its first check and every added-row group needed a hand cause. Because the daily ingests oldest first within a budget, this happens whenever a backlog is being worked off. Source: .cache/archive-release/release-20261110/causes/capture-address/README.md.

## Acceptance Criteria

The automatic rule keys on receipts absent from the live release's receipt set (by key), not on their date, or the limitation is documented with the hand procedure. A backlog ingest of only new rows passes without hand entries; a planted changed row is still refused.


## Notes

**2026-11-10T06:38:35Z**

2026-11-10 branch claude/ct-gate-rules: the automatic proof now keys on the receipt key alone. A new document's every capture line must sit in a receipt absent from the live release's receipt set, and the raw line must name the body; the key's date is no longer read. The set was already available to the gate: publish_candidate reads the live release's own input records (receipt_pins.kept_input_records, inputs/receipts/<sha256>.json.gz, digest-checked) and passes their union as live_receipt_keys, so nothing new is fetched. An empty set refuses. Tests that pinned the date rule on purpose were changed: an older-dated, an undated and a malformed-date key outside the live set now pass; the no-dated-receipt refusal became the empty-set refusal. Planted: a key the live release read, a body the live release also read under a backlog key, and a changed value beside backlog rows all refuse.

Real pair 630164505301 to 619db5f9e08e, per-row tests re-run offline (investigations/gate-rules-20261110/gc99-real-data.md; candidate capture_evidence in place of the lake captures table, live set as candidate receipts minus the review's 5,850 new keys, raw lines not read): 24,342 live receipts, newest dated 2026-11-07; 5,850 new, 4,339 of them dated 2026-10-31.
- added documents 731: date rule 149 pass, key rule 716. Remainder 15: 13 recovered documents (their key is a link key, no body to trace) and 2 printed-hearing HTM files whose body also sits in a 2026-09-28 receipt the live release read.
- added link keys 945: 149 then 729. Remainder: 201 on documents the live release has, 15 on those 15 documents.
- source rows at new addresses 1,757: 149 then 717. Remainder: 1,038 on documents the live release has, 2 on the HTM pair.
- rows under new lookup keys 2,377: 260 then 1,040. Remainder: 1,321 on existing documents, 16 on the 15.
- added URLs with attempts 910: 34 then 349. Remainder 561 have no qualifying fetch line of a passing new document.
The proof is still all or nothing, so last night would still have needed a record: values changed, and keys and addresses were added to existing documents. What changes is that a night that only adds documents from a backlog passes.

Cannot see, unchanged: a bug that adds only wrong rows from new receipts. New with the key rule: nothing checks that a receipt absent from the live set was not left out on purpose (no such mechanism exists today). Not done: recovered documents and additions on existing documents stay hand-explained; the ticket does not ask for them.
