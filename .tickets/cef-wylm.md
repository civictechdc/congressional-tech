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

