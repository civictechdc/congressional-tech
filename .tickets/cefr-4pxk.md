---
id: cefr-4pxk
status: closed
deps: []
links: []
created: 2026-10-28T13:58:29Z
type: bug
priority: 1
assignee: mikewolfd
---
# Provenance preflights distinguish metadata custody from byte consumption

Reuse main metadata custody checks for held provenance during daily/inventory preflight while preserving main stronger full-byte VerifiedFile.require at real consumers. Reproduce the four landing custody failures, test metadata/byte boundaries, focused production-offline checks and one CODE review.


## Notes

**2026-10-28T14:05:59Z**

Completed efcd70a5 contracts, f676cf1c main-method compatibility lift, ac111c90 explicit metadata-vs-byte test, d47ad835 metadata callers. The exact four landing identities reproduce body-open-before-admission under strong main require and pass after the caller fix. New tests independently require one actual full-hash open and reject an incorrect digest with valid metadata. Main _require_custody/require AST-identical; additional_hashes and consumer byte checks remain intact. Focused76PASS84.597s including daily native cases; existing shared7PASS1.161s. Independent CODE APPROVE/no findings. Source counts custody496→509; other caller line counts unchanged. No D1 SQL/receipt metadata, real storage action or main history merge. Root/release owns same-CI landing rerun.
