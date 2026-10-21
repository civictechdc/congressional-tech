---
id: ct-ur2y
status: closed
deps: []
links: [ct-tuez, ct-mi03, ct-r60e, ct-gfv8, ct-ur7v, ct-nloa, ct-csyg, ct-qkvr]
created: 2026-10-21T14:12:48Z
type: task
priority: 2
assignee: mikewolfd
tags: [news_lake, docspec, scale]
---
# Mint time-ordered news record ids so native key Updates prune by file

RunContext.new_id defaults to uuid.uuid4 (packages/news_lake/src/news_lake/context.py:88). docspec-rs replace_keys/read_keys prune retained files only by exact per-file key bounds (docspec-rs src/engine/write/key_points.rs, src/engine/read.rs). Random v4 ids give every file a key range covering nearly the whole id space, so every hourly append or upsert key-decodes every retained file: per-poll cost grows with total archive size, not with the batch. Time-ordered ids (UUIDv7, RFC 9562) cluster each poll's new ids into new files, so existing point pruning skips older files. Tracked engine-side in spicy-stack ss-wie5.

## Design

Switch the default id source to UUIDv7 (Python 3.14 uuid.uuid7, or a vetted RFC 9562 implementation on older runtimes); keep the lowercase canonical string form. Existing v4 ids stay valid and immutable; only new records get v7. Ids remain opaque in the contract (no semantics read from the timestamp bits). Callers that pass their own id_source for crash stability are unaffected.

## Acceptance Criteria

- New ids are RFC 9562 v7, lowercase, 36 chars, and sort by mint time across polls.
- Contract/semantics tests still pass; no stored v4 id is rewritten.
- Against the native backend, a second-poll upsert over N retained files decodes only files whose bounds contain an affected id (report files_scanned before/after for 1x and 10x retained archives).

