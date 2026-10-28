---
id: cefr-4pxk
status: in_progress
deps: []
links: []
created: 2026-10-28T13:58:29Z
type: bug
priority: 1
assignee: mikewolfd
---
# Provenance preflights distinguish metadata custody from byte consumption

Reuse main metadata custody checks for held provenance during daily/inventory preflight while preserving main stronger full-byte VerifiedFile.require at real consumers. Reproduce the four landing custody failures, test metadata/byte boundaries, focused production-offline checks and one CODE review.

