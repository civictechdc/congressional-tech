---
id: ct-te1p
status: closed
deps: [ct-2ukk]
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-aia9, ct-2yl5, ct-bwac, ct-gi01, ct-a3le, ct-0odd, ct-ec91, ct-3ttc, ct-84xa]
created: 2026-10-21T20:53:05Z
type: feature
priority: 1
assignee: mikewolfd
parent: ct-8kl2
tags: [r2, worker, viewer_publication, cloudflare, pdf]
---
# Idiomatic single-bucket public R2 (congressional-data.spicygov.ai -> congressional-tech-raw), Cloudflare WAF/Transform rules, PDF decompression with immutable body_key identity, and apps/viewer-data Worker retirement

Everything served from congressional-tech-raw is public civic data (.gov documents and ExportPin Parquet tables), yet apps/viewer-data/worker.mjs currently proxies every request through Worker CPU, bypasses CDN edge caching via env.PUBLICATIONS.get(), and gunzips PDFs in memory with Accept-Ranges: none (breaking HTTP 206 Partial Content PDF streaming).

## Design

Sequenced immediately after ct-2ukk completes:
1. Enforce the deferred-body SHA-256 exclusion gate (accepted-files.json) at ingest in raw_storage.py before uploading any body to /bodies/sha256/* (quarantining excluded hashes outside the public prefix).
2. Preserve Logical body_key Identity (CS 300 / evolutionary-refactoring invariant):
   - NEVER alter the logical body_key string ('bodies/sha256/<xx>/<sha256>.gz') in raw_archive or catalog rows, because document_index.py:454-456 hashes body_key into all 1.68M source_ids and document_index.py:548-553 hashes body_key into all 1.24M document_ids.
   - Store PDFs (data[:5] == b'%PDF-') uncompressed in R2 (at bodies/sha256/<xx>/<sha256>.pdf or with uncompressed PDF metadata) with ContentType='application/pdf', ContentDisposition='inline', and CacheControl='public, max-age=31536000, immutable' (plus a one-time R2 migration pass decompressing existing .gz PDFs, including ZIP-member PDFs). Have savedCopyUrl in catalog-v6.ts:291 (and/or a Cloudflare URL Rewrite Rule on /saved/<sha256>/<filename>) map (row.body_key, row.format) to the public R2 serving URL while keeping row.body_key bit-for-bit unchanged.
   - Store non-PDF bodies (HTML, bill/amendment XML, .doc, .docx, text, ZIP) gzipped with ContentEncoding='gzip', ContentType='application/octet-stream', ContentDisposition='attachment', and CacheControl='public, max-age=31536000, immutable'.
3. Attach congressional-data.spicygov.ai directly to congressional-tech-raw as a Public R2 Custom Domain with static Bucket CORS (AllowedOrigins: ['*'], AllowedMethods: ['GET', 'HEAD'], AllowedHeaders: ['Range', 'If-None-Match', 'Cache-Control'], ExposeHeaders: ['Content-Range', 'Content-Length', 'ETag', 'Last-Modified']).
4. Configure zero-Worker Cloudflare Edge Rules on congressional-data.spicygov.ai:
   - WAF Custom Rule: allow GET/HEAD only on /bodies/sha256/* and /exports/* (or /viewer-publications/*); block internal warehouse/receipt/quarantine prefixes (403 Forbidden).
   - HTTP Response Header Transform Rule: set Content-Security-Policy: sandbox; default-src 'none' and X-Content-Type-Options: nosniff when http.response.content_type ne 'application/pdf', and map ?filename=<encoded> on /bodies/sha256/* to Content-Disposition.
5. Delete apps/viewer-data/ (worker.mjs, wrangler.jsonc, worker.test.mjs). Once ct-2yl5 moves publication writes to docspec-rs Objects::Remote (which owns crash-recoverable .lifecycle state and conditional S3 writes), retire viewer_publication/continuation.py (1,500-line WAL for 8,192 JSON tree uploads) and GuardedPublicationClient's 2x full-readback verify(), keeping only a ~40-line conditional PUT (If-Match / If-None-Match) helper for the top-level manifest.json pointer.

## Acceptance Criteria

- All 1.68M source_ids and 1.24M document_ids remain 100% unchanged (row.body_key stays 'bodies/sha256/<xx>/<sha256>.gz').
- PDFs stream via native HTTP 206 Partial Content (Accept-Ranges: bytes) directly from congressional-data.spicygov.ai with CDN edge caching and no Worker.
- Non-PDF bodies download with Content-Disposition: attachment and Content-Security-Policy: sandbox; default-src 'none'.
- Internal warehouse/receipt prefixes return 403 Forbidden via WAF rule, excluded SHA-256 hashes are blocked at ingest, and apps/viewer-data/ is removed.
