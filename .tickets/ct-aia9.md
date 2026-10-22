---
id: ct-aia9
status: closed
deps: []
links: [ct-8kl2, ct-mi03, ct-czsd, ct-2ukk, ct-oc2g, ct-xu1o, ct-8ax6, ct-dzyf, ct-13cn, ct-dmca, ct-gziq, ct-n6lj, ct-sb0s, ct-te1p, ct-2yl5, ct-bwac, ct-gi01, ct-a3le, ct-0odd, ct-ec91, ct-3ttc, ct-84xa]
created: 2026-10-21T20:53:06Z
type: task
priority: 2
assignee: mikewolfd
external-ref: ss-8tpu
parent: ct-8kl2
tags: [congress_shared, docspec_client, custody, r2, deduplication]
---
# Extract congress_shared.custody + connect_r2 and consolidate shared Arrow schema adapter in packages/docspec_client

Across congress_api/retention, viewer_publication, corpus_recovery, news_lake, and scripts/publication, there are 15 copy-pasted atomic file writers, 9 SHA-256 file helpers, 4 stat-custody tuples, 7 canonical JSON / self-binding receipt encoders, 5 boto3 R2 client factories, and duplicate JSON-Schema <-> Arrow converters in news_lake/storage/docspec_backend.py.

## Design

1. Extend packages/congress_shared with congress_shared.custody and connect_r2:
   - VerifiedFile, file_identity(path), custody_identity(path), copy_checked(src, dst), write_atomic_bytes(path, data, temp_mode='unique' | 'fixed', mode=None) (supporting both unique mkstemp and deterministic .tmp crash-cleanup per ct-2d3k), write_atomic_json(path, obj), canonical_json_bytes(obj), write_bound_receipt(path, body), read_bound_receipt(path), iter_canonical_digest(items), and connect_r2(...).
   - Per evolutionary-refactoring (SKILL.md:48-51, do not create cross-package surface area for a single consumer): keep R2Store / LocalStore inside congress_api/retention once viewer_publication is retired (since news_lake and committee_explorer only talk to docspec_client).
2. Move the shared JSON-Schema / Pydantic <-> Arrow schema adapter into packages/docspec_client (paired with spicy-stack ss-8tpu native UInt64/Binary coercion and Arrow IPC write streaming), deleting the duplicate schema coercion and DocSpecClient wrapper in news_lake/storage/docspec_backend.py:89-204, 347-495.

## Acceptance Criteria

- All 15 atomic file writers, 9 SHA-256 helpers, 7 receipt binders, and 5 boto3 R2 client factories delegate to congress_shared.custody and connect_r2, while R2Store/LocalStore remain cleanly scoped to congress_api.
- Both temp_mode='unique' and temp_mode='fixed' crash-cleanup invariants (ct-2d3k) pass existing test suites.
- news_lake and congress_api share a single Arrow schema adapter in packages/docspec_client.
