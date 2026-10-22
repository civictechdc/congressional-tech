---
id: ct-a3le
status: closed
deps: [ct-n6lj]
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-aia9, ct-2yl5, ct-bwac, ct-gi01]
created: 2026-10-21T20:53:32Z
type: task
priority: 2
assignee: mikewolfd
external-ref: ss-023x,ss-65bz,ss-6gwu
parent: ct-8kl2
tags: [news_lake, site, docspec, cleanup]
---
# Migrate news_lake upserts & bridges to UpdateMergeSpec / chained RefreshSpecs, preserve cross-table C5 expiry redaction, retire legacy .json.gz exports, and decouple apps/site from docs/youtube-coverage

news_lake/storage/docspec_backend.py (1,681 lines) still maintains a Python read_keys -> merge_upsert_batch loop and Python bridge/view assembly (ct-n6lj), plus legacy .json.gz sharded exports (news_lake/export.py, query.py). Meanwhile, 11 production/test files in apps/site, viewer_publication, and CI workflows still import from docs/youtube-coverage/research/.

## Design

1. In news_lake:
   - Replace _commit_upsert's Python read_keys loop with UpdateSpec UpdateMergeSpec(order_by='recorded_at') (ss-023x, LatestOrBackfill + SetUnion + Min/Max, which is algebraically closed under validate_shape after _prepare validates incoming records).
   - Replace update_bridges and _assemble_politician_articles with chained RefreshSpecs including 2-stage cross-date syndication (ct-n6lj, ss-65bz).
   - Preserve cross-table C5 capture-expiry semantics (news_lake/analysis/export.py:83-108, where version.capture_id in expired_captures depends on captures.retain_until < now): either denormalize capture_retain_until onto news_versions (via RefreshSpec / ingest) so ExportPolicy (ss-6gwu) can redact single-table, OR retain the 110-line export.py C5 gate for the 2 body-bearing tables (captures, versions) while the other 8 tables continue using direct ExportSpec (ct-4nyy).
   - Retire legacy .json.gz sharded news exports.
2. In apps/site and CI: repoint viewer-ui.test.mjs, markup.test.mjs, adapter.test.mjs, and detail-state.test.mjs to test apps/site/src/components/explorer/** directly; move committee-explorer-preview.json into apps/site fixtures; remove view_document_filenames.py from CI/release fingerprints; and delete the duplicate vanilla-JS prototype files in docs/youtube-coverage/.

## Acceptance Criteria

- news_lake/storage/docspec_backend.py performs zero Python read_keys upsert merges and zero full-corpus Python bridge scans (ct-n6lj), while 100% preserving C1-C5 contract invariants (including cross-table version redaction when a referenced capture expires).
- Zero files in apps/site, packages/*, scripts/*, or .github/workflows/* import or hash files under docs/youtube-coverage/.
