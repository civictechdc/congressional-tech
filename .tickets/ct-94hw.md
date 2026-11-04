---
id: ct-94hw
status: in_progress
deps: []
links: [ct-m56x]
created: 2026-11-04T15:19:41Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [daily, nightly, custody, phase2]
---
# Daily reads unpinned bodies through a candidate-scoped R2 listing, checked before captures append

Nightly 20261104T143713Z stopped with RawCustodyRequired: 5 of 5000 readings candidates had no captured stored MD5/size. 85 unread bodies are in that state (5 Oct 31 meeting bodies, 80 Oct 15 bulk-uploaded documents/transcripts): they were uploaded by runs that wrote no receipt, and the later conditional PUT got 412 and recorded outcome=unchanged without pins. Captures appended before readings planned, so the refusal left 5000 appended-but-unread captures. Evidence: .cache/archive-release/investigations/nightly-unpinned-captures-20261104.md. Nightly launchd job unloaded until this lands.

## Design

All in daily.py (no hashed parser touched): before append, count the pending readings backlog and shrink the budget by it; HEAD every candidate body's recorded R2 key into a candidate-scoped listing (quoted ETag); refuse before append if an object is missing; plan readings in the planner's listing mode; report RawCustodyRequired as a status. Branch nightly-listing.

Owner decisions 2026-11-04: read the 85 bodies; SHA-256 verification at read time is sufficient custody. Provenance: the Oct 31 scheduler runs 7aab36630668 and acc7ca3dd55a were interrupted local runs; the Oct 15 bodies came from an owner-run bulk import.

## Acceptance Criteria

Planted wrong ETag/size and unquoted ETag refused; missing candidate fails closed; missing object refuses with no append; budget selects at most max_work_items minus backlog; nightly re-enabled and a run publishes.

