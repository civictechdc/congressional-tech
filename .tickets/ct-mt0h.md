---
id: ct-mt0h
status: open
deps: []
links: []
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
