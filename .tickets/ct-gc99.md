---
id: ct-gc99
status: in_progress
deps: []
links: [ct-9j3z, ct-ud0b]
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

**2026-11-10T07:45:50Z**

2026-11-10 after the independent review (investigations/gate-rules-20261110/review/REVIEW.md):
- Cap (point 6). AUTOMATIC_ADDITION_CAP = 250 documents per unattended night; above it the automatic proof returns a reason and the groups need a record. Values of added rows are never compared, so a large batch waits for a person. Chosen from the two nights measured: the single capture day in 619db5f9e08e added 151 documents, its week-old backlog 567 more (731 with recoveries). Two data points only; the owner should tune it once nightly capture has a history. Consequence: last night's backlog would still have needed a record.
- Receipt reads (point 5). Confirmed: the proof read raw receipts through the publication client, which must keep total_max_attempts 1. publish_candidate now takes receipt_client, and the job passes the same retrying read client the daily uses for bodies (configure_read_retries, five attempts on GET), so one transient error among thousands of reads no longer ends the night.
- Retired ledger (point 4). Not changed, with evidence: the gate already refuses. A key published again must leave the ledger (the export refuses a key in both), which makes a retired_links removed-keys group, and that group is not an addition, so the automatic proof stops at its first check. The new test test_a_removed_document_that_comes_back_is_not_a_new_document plants the reviewer's case and passes before and after (review-gc99-tests-before.log).
- The real function on the real pair (point 7, investigations/gate-rules-20261110/gc99-real-automatic-causes.md). require_release_gates with automatic_causes as publish_candidate wires it, the pinned local engine, the candidate's capture evidence (4,176,147 rows) in place of the lake table, and the live release's own receipt list (24,342 keys, fetched from the public origin and confirmed by its content address; it equals the stand-in set of the first proof). Output: no entries; 94 reasons of the form 'X is not an addition that can be traced', because the release changed values. Shown only the addition and citation groups, the same function answers: 731 added documents, more than the 250 one unattended night may add; 1038 sources rows were added to existing documents; 1321 urls rows were added to existing documents; 945 added link keys, 744 attached to new documents. These equal the offline table (1,038, 1,321, and 729 + 15 = 744). It returns before its document trace whenever a reason stands, so the trace query and the raw reads have still not run on real data: the private raw bucket is not readable here, and production may hold a second input record under the live prefix that could not be listed.
