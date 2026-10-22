---
id: ct-ec91
status: closed
deps: []
links: [ct-0odd, ct-aia9, ct-te1p, ct-3ttc, ct-gi01, ct-8kl2, ct-2yl5, ct-bwac, ct-84xa]
created: 2026-10-22T04:03:02Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-8kl2
tags: [r2, pdf, migration, raw_storage]
---
# Backfill uncompressed .pdf objects in congressional-tech-raw R2 for existing accepted-files.json PDF bodies

New PDF captures are stored uncompressed at bodies/sha256/<xx>/<sha256>.pdf while preserving row['body_key'] = 'bodies/sha256/<xx>/<sha256>.gz' identity. Existing historical PDF captures in congressional-tech-raw that only exist at .gz should have their uncompressed .pdf sibling object populated so browser PDF viewers can range-request them directly.

## Design

1. Iterate over PDF entries in accepted-files.json where format/media_type is application/pdf.
2. For each sha256 where bodies/sha256/<xx>/<sha256>.pdf does not yet exist in congressional-tech-raw, stream-decompress bodies/sha256/<xx>/<sha256>.gz, verify the decompressed bytes match the expected sha256, and upload bodies/sha256/<xx>/<sha256>.pdf with Content-Type: application/pdf and Cache-Control: public, max-age=31536000, immutable.
3. Keep the original .gz object intact during transition.

## Acceptance Criteria

1. Every accepted PDF in accepted-files.json is addressable at https://congressional-data.spicygov.ai/bodies/sha256/<xx>/<sha256>.pdf with HTTP 206 Range support and verified SHA-256 content.

