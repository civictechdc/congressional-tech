---
id: ct-j9c4
status: open
deps: [ct-snzi]
links: []
created: 2026-10-24T18:15:53Z
type: task
priority: 0
assignee: mikewolfd
parent: ct-v967
---
# Confirm the daily capture resumes and writes correct stored_sha256

No raw captures have run since about Oct 19. Hosted capture failed from Oct 21 to Oct 24, first on packaging and then on a stale engine pin; the pin was fixed on Oct 24 and `54a68ac7` stopped the digest backfill. The next scheduled capture is the first chance to resume.

## Acceptance Criteria

- A scheduled capture run succeeds; its run id is recorded here.
- New receipts appear under `receipts/`, and R2 checks 1 and 2 pass.
- New capture rows for gzip bodies carry the stored object's digest in `stored_sha256` (or null when unknown), not the content hash.


## Notes

**2026-10-24T18:47:54Z**

Also check, after the first capture run, that new compressed (gzip) capture rows carry stored_sha256 different from sha256 and equal to the stored object's hash (fix 54a68ac7).
