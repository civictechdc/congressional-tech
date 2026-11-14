---
id: ct-tpwm
status: in_progress
deps: []
links: [ct-l47f, ct-6v77, ct-cbkz]
created: 2026-11-14T15:56:14Z
type: bug
priority: 1
assignee: mikewolfd
tags: [source_quality, body_text, followup]
---
# Bound native append membership memory to incoming keys

The markup adoption reached 1,494,759 historical/current reading rows. The existing-key RIGHT ANTI hash build then exceeded its 256 MiB fair-pool share even though incoming chunks were below 8 MiB and process RSS was only 0.750 GiB. Chunk splitting cannot bound a hash table built from all retained keys. PR166 solved incoming payload placement; this is its separately measured key-growth followup.

## Design

Use a narrow incoming-key LEFT SEMI match over the stored keys, then RIGHT ANTI against incoming payload. The stored history streams; both build sides are bounded by incoming keys even if stored keys repeat. Preserve exact full/null-safe tuples, existing values, native CAS recomputation, source-hashed work identity and no-op behavior. Implementation at 6ab88fed7d6dad780b9e1475360bfd3144134eca passed independent review; final bounded adoption is running.

## Acceptance Criteria

Pass focused native null/binary/empty/duplicate/conflicting-value cases; replay the exact failed 4,237-row piece against the actual 1,494,759-row snapshot under unchanged limits; force and observe a real concurrent native CAS retry without duplicate/lost rows; resume the remaining 22 pieces and reconcile all 310,963 reading keys plus unchanged historical rows. Retain failure and all receipts.


## Notes

**2026-11-14T16:03:03Z**

Independent reviewer approved exact 6ab88fed and independently read all 4,237 failed-piece rows plus the real native CAS catalog: 2,049 keys/text hashes match and the prior value is preserved. Review used 0.51 GiB RSS / three seconds. Certificate SHA 5d6f0ca0091b01a8af8329d811783fa349fbd492583d219121ca2eb3aa582c31 under local-adoption-20261114/append-key-bound-20261114/independent-review/. Final 22-piece adoption is now resuming under unchanged limits, with prior receipts reused.
