---
id: ct-ec91
status: closed
deps: []
links: [ct-0odd, ct-aia9, ct-te1p, ct-3ttc, ct-gi01, ct-8kl2, ct-2yl5, ct-bwac, ct-84xa, ct-syx8]
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


## Audit 2026-10-24

- Verdict: PARTIAL (batch kl2a1aa).
- Grades: proposal 78 → 78, work 70 → 70.
- Problem: The backfill tool landed, but production ingest never writes uncompressed PDFs, its default `--accepted-files` path does not exist, and nothing shows it ran.
- Evidence: docs/reviews/2026-10-24-ticket-audit/batches/kl2a1aa/kl2a1aa-verdicts.md:30
- Status: Closed as superseded by the simplification plan (WS2, ct-syx8): the owner deleted the exclusion-list hook, so `accepted-files.json` is no longer an input; whether `.pdf` siblings are written at all is plan open question 5, and if they are, WS2 step 5 folds the PDF migration into this backfill with the catalog as input.
- See docs/reviews/2026-10-24-ticket-audit/README.md
