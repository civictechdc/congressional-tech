---
id: ct-mt0h
status: closed
deps: []
links: [ct-r4rd]
created: 2026-10-31T13:51:46Z
type: feature
priority: 1
assignee: mikewolfd
external-ref: gh-149
tags: [release, data-model, search, spicyengine]
---
# Release data model: a keyed document table (link_key with list's columns) and congress on meetings

list.parquet carries no id by design; the stable key link_key lives in detail.parquet, same row order. Machine consumers (SpicyEngine, explorer MCP, cross-release joins) must zip the two files by row position. Proposal: make detail.parquet the document table by adding list's columns (about 5 MB on 21 MB) and keep list.parquet as the browser projection; alternative: add link_key (hex, 16 chars) to list.parquet. Also add congress to meetings.parquet (pending in the phase-2 annex). Longer term: materialize current-state documents/meetings/witnesses into the Basin catalog as Iceberg tables pinned by snapshot so a search server points at the namespace. Context: SpicyEngine 0.17 indexes the published files as one generation (532,743 rows); 0.18 zips list+detail by row as a workaround to key documents by link_key. GitHub issue #149 holds the same text.

## Acceptance Criteria

A release carries the document key in the same table as title and facets; meetings.parquet has congress; SpicyEngine's row-aligned document source is retired in favour of one keyed table.


## Notes

**2026-11-01T20:08:14Z**

Owner decision 2026-11-01: detail.parquet becomes the keyed document table by adding list columns; list.parquet stays the no-ID browser projection (data model §8.1). Measure both options on the live release before changing the schema. congress on meetings is delivered with ct-r4rd; do not implement it twice.

**2026-11-02T04:01:45Z**

Code on worktree-agent-a704015cc138b456b @ da425206. Review verdict: merge. Open: detail size after rebuild; SpicyEngine retirement not verified.

**2026-11-05T17:11:18Z**

Archive-side delivery complete in e145d24c389e. Installed MCP stdio readback against the verified public selection confirms detail.parquet contains link_key and every list column: 356,735 rows in 26,880,700 bytes. Direct detail-only SQL returned key a1e328fa668b0649 with title and committee/Congress facets. meetings.parquet exposes congress. Matched SpicyRegs value parity stays with ct-r4rd. Remaining SpicyEngine adoption of this one keyed table and retirement of the row-aligned adapter/tests is explicitly transferred to the existing open spicy-stack ss-7ih1, which receives the release proof. This closure does not claim downstream indexing or adapter retirement has happened. Evidence: docs/engine-first-data-model.md §8.1 and the e145 publication-approved live manifest/readback.
