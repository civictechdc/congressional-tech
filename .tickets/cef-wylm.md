---
id: cef-wylm
status: in_progress
deps: []
links: []
created: 2026-10-28T01:07:54Z
type: task
priority: 1
assignee: mikewolfd
---
# Read retained bodies once for pinned sniff and page evidence

D2 owner read-once decision: metadata-first native per-body admission/worklist, reuse lake and qualified old-index facts, one bounded raw-object read or stream per consumer, produce sniff and actual page evidence from the same bytes, preserve supervised parser failures and pending raw reads. Measure format-route populations before any real body run; tests cover mislabeled MIME, unknown/gzip pages, skipped known formats, duplicates and versioned reuse. Fold PLAN6.4item2/BIND and commit one short audit note. Full live backfill remains owner-gated.


## Notes

**2026-10-28T05:11:54Z**

Ownership transferred to raw by owner decision 20261028T051000Z. Current clean producer changes are committed through b8708a47 (shared current writer proof/conflict query), 736ee8b3 (CODE fixes), 9ce978e4 (read once), and23f7d5ea (shared proof SQL). Native focused22PASS37.91s/current real50 bodies1.966s/1230266B. Root retains model admission consumers, raw owns all further producer work and done-when/full backfill.
