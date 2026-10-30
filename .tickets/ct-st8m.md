---
id: ct-st8m
status: closed
deps: []
links: []
created: 2026-10-24T18:15:53Z
type: task
priority: 1
assignee: mikewolfd
parent: ct-v967
---
# Reconcile accepted.json with the receipts

`viewer-publications/recoveries/accepted.json` is mutable and sits under a derived prefix (audit raw risk 6). Checked directly: only 11,597 of its 24,028 recoveries appear in receipts (`record.recovery_evidence` or `source_associations`). 12,431 exist only in the file (12,419 of them `user_accepted_url_variant`), 1,172 receipt recoveries are missing from the file, and 269 bases and 57 recovered URLs differ. A verified backup is at `provenance/recoveries/accepted-00922c1e….json`.

This is plan P5 (audit open item 6) and blocks WS6 step 5, which moves the mapping into the release flow.

## Acceptance Criteria

- A read-only comparison of the file against the receipts, committed under `docs/` (not the gitignored `output/`), explains each class of difference: file-only, receipt-only, basis and recovered-URL.
- The owner records whether `accepted.json` is provenance.
- If it is, the file-only decisions gain a raw provenance record (receipts or `provenance/`) before WS6 moves the mapping. Nothing is deleted.


## Notes

**2026-10-24T18:47:54Z**

After reconciling, stop rewriting accepted.json whole on each publish (O(A), mappings.py:44-78): derive it from receipts, or publish append-only deltas (E11).

**2026-10-30T16:49:24Z**

Verified completed via cefr-8q3p (commits 0a55702e and 87bc28fd), cefr-7cj1 (commits ac9a747c and 7a8c74a6), and F5 G12 (commit 8978b3bb): all 24,028 recovery decisions in accepted.json and receipt recoveries were reconciled via packages/corpus_recovery/src/corpus_recovery/reconcile.py with write-once provenance under provenance/recoveries/ and measurements committed under docs/measurements/engine-first-20261027/b7/, and legacy mappings.py was deleted in commit 8978b3bb.
