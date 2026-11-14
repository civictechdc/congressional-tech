---
id: ct-tpwm
status: closed
deps: []
links: [ct-l47f, ct-6v77, ct-cbkz]
created: 2026-11-14T15:56:14Z
type: bug
priority: 1
assignee: mikewolfd
tags: [source_quality, body_text, followup]
---
# Bound native append membership memory to incoming keys

Merged in PR #169 at 43bef91c5378eb6c5e55ef0ff0bf1b64a3fe7674 after all CI passed. Incoming-key membership now bounds native append memory independently of stored history. The original 4,237-row failure replay, real concurrent CAS and the entire remaining markup adoption pass under the unchanged limits. All 310,928 texts and 310,963 reading rows are adopted; all prior outcomes remain intact.

## Design

Use a narrow incoming-key LEFT SEMI match over the stored keys, then RIGHT ANTI against incoming payload. The stored history streams; both build sides are bounded by incoming keys even if stored keys repeat. Preserve exact full/null-safe tuples, existing values, native CAS recomputation, source-hashed work identity and no-op behavior. Implementation at 6ab88fed7d6dad780b9e1475360bfd3144134eca passed independent review; final bounded adoption is running.

## Acceptance Criteria

Pass focused native null/binary/empty/duplicate/conflicting-value cases; replay the exact failed 4,237-row piece against the actual 1,494,759-row snapshot under unchanged limits; force and observe a real concurrent native CAS retry without duplicate/lost rows; resume the remaining 22 pieces and reconcile all 310,963 reading keys plus unchanged historical rows. Retain failure and all receipts.


## Notes

**2026-11-14T16:03:03Z**

Independent reviewer approved exact 6ab88fed and independently read all 4,237 failed-piece rows plus the real native CAS catalog: 2,049 keys/text hashes match and the prior value is preserved. Review used 0.51 GiB RSS / three seconds. Certificate SHA 5d6f0ca0091b01a8af8329d811783fa349fbd492583d219121ca2eb3aa582c31 under local-adoption-20261114/append-key-bound-20261114/independent-review/. Final 22-piece adoption is now resuming under unchanged limits, with prior receipts reused.

**2026-11-14T16:48:29Z**

Closed after merged implementation and completed data gate. Final markup reconciliation SHA 470dd9a144d88959498be2682fee19b411c28bbe1c71b3b6294c829a7beee775 at repairs/markup-reparse-20261114/local-adoption-20261114/final-verification-02/result.json has zero missing/extra/status/hash differences. A further 945 text/reading pairs passed 125 exact native append/readback receipts at 0.464 GiB peak RSS; root independently verified every receipt hash, ordered snapshot ancestry, 945 matching key sets and no deletes. Native limits stayed 512 MiB pool/256 MiB scratch, watchdog 1.8 GiB. Adoption is not automatic selection or publication.
