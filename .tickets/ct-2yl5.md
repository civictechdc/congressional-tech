---
id: ct-2yl5
status: open
deps: [ct-2ukk, ct-oc2g]
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-bwac, ct-gi01, ct-a3le, ct-0odd, ct-ec91, ct-3ttc, ct-84xa, ct-qqk2]
created: 2026-10-21T20:53:06Z
type: feature
priority: 1
assignee: mikewolfd
external-ref: ss-6gwu,ss-yjvy
parent: ct-8kl2
tags: [viewer_publication, docspec, export, hyparquet]
---
# Replace viewer_publication custom Parquet/Brotli repacking (filename_native.py, details.parquet, observations.bin) with zero-copy docspec-rs ExportSpec (ExportPin) and flat child occurrences.parquet

packages/viewer_publication (22 files) currently reads docspec-rs Parquet leaves back out into Python, stages SQLite scratch tables (NativeComponents in filename_native.py), writes duplicate copies of filenames.parquet and documents.parquet, repacks sparse house_naming columns into details.parquet (filename_details.py), packs source_occurrences into custom Brotli .bin files (observations.bin), and builds 16-way JSON prefix trees (roots.sources, roots.components, roots.browse) that require 4 sequential HTTP GET round-trips per lookup.

## Design

Sequenced after ct-2ukk, ct-oc2g, and spicy-stack ss-6gwu / ss-yjvy:
1. Configure docspec-rs ExportSpec (ExportPolicy, ss-6gwu) for filenames and documents to join column groups (read_combined across source + house_naming + EvidenceSpec), project non-null house_naming columns into a compact filename_readings: List<Struct<field, values>> struct-list column (so detail reads fetch 1 column chunk instead of 300, eliminating details.parquet), strip __docspec_* internal columns, sort by order_by with selective scalar-column PageIndex (acting directly as an O(1) HTTP 206 Range B-tree without 16-way JSON prefix trees), and emit GROUPING SETS facet counts + browse pagination ranges.
2. Export source_occurrences as a flat sorted child Parquet table occurrences.parquet ((owner_id, occurrence_order, ...), ss-yjvy) with 2,048-row groups and selective PageIndex on owner_id so catalog-v6.ts observationPage(id, {offset: 0, limit: 20}) reads 20 flat rows (~150 KB, <1% of the 64 MiB worker cap) via hyparquet without custom Brotli observations.bin.
3. Update apps/site/src/components/explorer/reader/filenames/catalog-v6.ts to read browse pages, facet counts, single-row details, and 20-item occurrence slices directly from the ExportPin Parquet files on congressional-data.spicygov.ai, and retire filename_native.py's custom repacking, filename_details.py, filename_observations.py, filename_json_stream.py, filename_viewer.py (770-line embedded HTML template), continuation.py, and observations.ts.

## Acceptance Criteria

- Browser catalog-v6.ts reads browse pages, facet counts, single-row details (including filename_readings), and 20-row occurrence pages (<1 MiB worker memory on the 33,479-occurrence outlier document) directly from docspec-rs ExportPin Parquet files via hyparquet byte-range requests.
- Zero duplicate Parquet (details.parquet), Brotli .bin (observations.bin), or 16-way JSON tree files are written outside docspec-rs ExportSpec.
- packages/viewer_publication is collapsed to a thin declarative export/manifest coordinator.

## Audit 2026-10-24

- Verdict: PARTIAL (batch kl2a1aa).
- Grades: proposal 84 → 84, work 62 → 62.
- Problem: AC2 ("zero details.parquet/observations.bin/JSON tree files") and AC3 ("thin coordinator"; the package is 9,661 lines, with filename_native 1,067, filename_viewer 871 and continuation 492) are unmet.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:37
- Status: Reopened. Unmet: AC2 (no `details.parquet`, `observations.bin` or JSON tree files) and AC3 (a thin coordinator); the unwired export-pins publish also writes a dangling pointer. Owner: WS6 (ct-qqk2), which makes export-pins the only route.
- See docs/reviews/2026-10-24-ticket-audit/README.md
