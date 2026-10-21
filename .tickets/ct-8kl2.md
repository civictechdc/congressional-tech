---
id: ct-8kl2
status: open
deps: [ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-2yl5, ct-bwac, ct-gi01, ct-a3le]
links: [ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-2yl5, ct-bwac, ct-gi01, ct-a3le]
created: 2026-10-21T20:52:42Z
type: epic
priority: 1
assignee: mikewolfd
external-ref: ss-55jg
tags: [architecture, docspec, r2, end-state, deduplication]
---
# Converge on docspec-rs end-state architecture and idiomatic single-bucket public R2 (congressional-data.spicygov.ai)

Parent epic tracking the end-state convergence across congressional-tech: making docspec-rs (DataFusion 53 + Rust) the sole table, timestamp-ordered upsert (UpdateMergeSpec), multi-source provenance aggregation (AggregateTransform), connected-components, join/rollup, and zero-copy ExportPin engine across all 3 domains (Archive/Catalog, Committee Explorer, News Lake), and serving congressional-tech-raw directly via public R2 Custom Domain (congressional-data.spicygov.ai) with uncompressed PDFs, immutable body_key identity, and zero Cloudflare Worker.

## Design

See ideal_end_state_proposal.md and architecture_and_duplication_trace.md (including Section 8 CS 300 Systems Review, Section 9 Ticket Cross-Check, and Section 10 Evolutionary Refactoring Adjudication):
1. Complete ct-2ukk and ct-oc2g first to finish the live catalog-v6.ts cutover (closing epic ct-czsd) without disruption, and complete ct-xu1o / ct-8ax6 / ct-dzyf alongside spicy-stack ss-g9sn / ss-7hrv / ss-onwi.
2. Pillar 1: Replace viewer_publication custom Parquet/Brotli/JSON-tree repacking (filename_native.py, details.parquet, observations.bin) with zero-copy docspec-rs ExportSpec (ExportPin) + flat child occurrences.parquet + compact filename_readings projection (ct-2yl5, paired with ss-6gwu & ss-yjvy); flatten congress_api/retention routing/splitting/staging (RoutingPages, CatalogRows, 3 Union-Find engines) into native docspec-rs operators (ct-bwac, paired with ss-023x, ss-k3mg, ss-yjvy, ss-msdx); migrate committee_explorer (eliminating the 15.3 GB RAM / 20 GB swap CI bottleneck) and the 9 weekly .json.gz/CSV retention modules onto incremental docspec-rs tables (ct-gi01); and finish ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s against the upgraded engine (ss-65bz, ss-vfm6).
3. Pillar 2 (ct-te1p): Attach congressional-data.spicygov.ai directly to public congressional-tech-raw with static Bucket CORS, Cloudflare WAF prefix allowlist, Response Header Transform Rules (conditional CSP: sandbox on non-PDFs + ?filename= Content-Disposition), ingest SHA-256 exclusion gate (accepted-files.json), and uncompressed PDFs (206 Partial Content) while keeping row.body_key ('bodies/sha256/<xx>/<sha256>.gz') immutable so all 1.68M source_ids and 1.24M document_ids are preserved; retire apps/viewer-data/worker.mjs and continuation.py.
4. Pillar 3 (ct-aia9): Extract congress_shared.custody + connect_r2 (keeping R2Store/LocalStore in congress_api) and consolidate the shared Arrow schema adapter in packages/docspec_client (paired with ss-8tpu).
5. Pillars 4 & 5 (ct-a3le): Migrate news_lake upserts/bridges while preserving cross-table C5 capture-expiry semantics, retire legacy .json.gz exports, and decouple apps/site tests from docs/youtube-coverage/research/filename-*.mjs.

## Acceptance Criteria

All child tickets and reopened ct-mi03 tickets (ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-dzyf, ct-8ax6) are completed, apps/viewer-data Worker, 20 GB CI swap file, and Python SQLite/DuckDB scratch layers are retired, all 1.68M source_ids and 1.24M document_ids remain unchanged, and zero production/test files import from docs/youtube-coverage.
