---
id: cef-s4vp
status: closed
deps: []
links: []
created: 2026-10-28T07:55:35Z
type: bug
priority: 1
assignee: mikewolfd
---
# Match acknowledged record MD5s with provider ETags

Daily raw records return an acknowledged unquoted single-PUT MD5, while provider LIST returns its quoted ETag. Compare these known record checksums by normalized MD5 while keeping every non-record provenance ETag opaque and exact. Preserve current-inventory refusal and no payload reads.


## Notes

**2026-10-28T08:06:37Z**

Binding d768355e passes the quoted/unquoted record MD5 fixture, unchanged opaque backup tokens and stale-inventory refusals with zero GETs. Combined focused group109PASS36.30s/71cc6eb. Independent CODE review APPROVE/no findings (cx_fixture_etag_review/review.md). Actual provider LIST ETags remain in complete input identity.
