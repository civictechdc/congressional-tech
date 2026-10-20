---
id: ct-5yof
status: closed
deps: []
links: []
created: 2026-10-20T16:52:23Z
type: feature
priority: 2
assignee: mikewolfd
parent: ct-a1aa
tags: [news-lake, analysis, export]
---
# Implement typed-label classification producer and restricted-export enforcement gate

04-implementation-plan.md Slice 6 specifies 'One clusterer, typed labels and release-scoped views' and line 14 requires 'restricted-export, retired-snapshot, Unicode-offset, schema-evolution and concurrent-acquisition tests'. Currently, news.classifications has no producer or view reader in packages/news_lake, and C5 ('Exporters MUST omit unauthorized bodies' and honor retain_until expiry) has no export helper or regression test.

## Design

1. Add a deterministic offline baseline classification producer in news_lake/analysis/ (emitting contract-valid classification records with a documented run, dimension, taxonomy_version, and typed value) and expose selected classifications in analysis/.
2. Add a release-scoped export function (e.g., export_release) that enforces C5 access rules (omitting restricted payload_uri/text/rights_basis or downgrading restricted versions to metadata_only on public export unless authorized, and enforcing retain_until expiry) and add restricted-export regression tests.

## Acceptance Criteria

- The baseline classification producer emits shape- and corpus-valid run + classification records that round-trip through Iceberg and C8 run selection.
- Public/unprivileged export omits restricted article bodies and expired payloads per C5 while preserving redistributable and metadata_only fields, verified by restricted-export tests.


## Notes

**2026-10-20T17:30:52Z**

Added deterministic keyword topic/tone classification producer and C5 export_release enforcing restricted/expired body omission, redistributable preservation, authorized bypass, and input immutability. Labels/export tests: 13 passed.
