---
id: ct-63hg
status: open
deps: [ct-snzi]
links: [ct-v9ua]
created: 2026-10-24T18:15:53Z
type: task
priority: 0
assignee: mikewolfd
parent: ct-v967
---
# Check the selected native capture index for rows with a wrong stored_sha256 written Oct 22-24, and repair them in place

From `48137619` (Oct 22) until `54a68ac7` (Oct 24), `raw_values._to_legacy_capture_table` filled `stored_sha256` with the content hash whenever a new capture row had none. That is wrong for gzip bodies (audit raw risk 3; ct-v9ua). Receipts are correct. `indexes/raw.json` was rewritten 2026-10-23 05:21 UTC, and local runs between Oct 22 and Oct 24 wrote about 141k `indexes/native-manifests/` objects and many `source-observations-members-*` datasets, so the selected native capture index may hold wrong rows.

Plan open question 3 is answered: repair the rows in place, do not regenerate the index from receipts.

## Acceptance Criteria

- A read-only pass over the selected capture table lists every row written Oct 22-24 whose `stored_sha256` differs from the receipt's stored digest (or from the stored object's sha256); the count is recorded here, including zero.
- If any exist, those rows are repaired in place through the engine (a keyed update from receipt values), verified row for row after the write.
- R2 check 1 (every earlier `receipts/` and `bodies/` key unchanged) and check 2 (every `receipt_key` exists) pass before and after.

