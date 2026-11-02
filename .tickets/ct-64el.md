---
id: ct-64el
status: open
deps: []
links: [ct-sh4j, ct-qg8e, ct-gi01, cef-96wc, ct-o2pr, ct-lgxk]
created: 2026-11-02T00:36:42Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-77zb
tags: [release, model, eligibility, phase2]
---
# Treat ZIP contents as the documents; a ZIP is only how files were captured

Owner decision 2026-11-01: ZIPs are capture transport and do not belong in the documents table; what they contained does. Publish_v21 dropped all 68,785 member source rows because members have no completeness field of their own: raw receipts read for all 68,785 show every ZIP complete and expanded and every member entry completed, though ZIP bytes were not re-read. Effects: ZIP-format list rows 363 to 34,039, 34,157 split documents, 7,194 member-only link keys gone, alternates 69,273 to 1,509. Cause traced to bc0a146c (code) and 87dc8905 (rule text); the data model conflicts at §6.1 line 243 and §7.3 line 476, and the fixture manifest says the ZIP joins the document. Evidence: docs/measurements/release-diff-c94bfedc-448651e7-20261101.md.

## Acceptance Criteria

- Data model amended: §6.1, §7.3, §8.2 and the S1 fixture state that contents are the documents, manifests join none, and the ZIP is a source record.
- Eligibility: a member counts when its exact container attempt is complete and expanded, checked by a semi-join so duplicate container rows cannot fan out; 12 HTTP 206 members are decided by the raw facts rather than restored in bulk. The retry fix for direct bodies stays.
- No ZIP rows in list or alternates, except a recorded disposition for ZIPs with no expanded contents.
- Published ZIP link keys and URLs resolve to the document; sources keep the ZIP URL and member path.
- A rebuild shows grouping and links, accounted by key against c94bfedc and 448651e7. Also measure from raw how many of the 242,293 top-level NULL-complete rows are wrongly excluded.


## Notes

**2026-11-02T04:01:45Z**

Code on worktree-agent-a704015cc138b456b @ da425206. Review verdict: merge, stay open. Raw: 15/15 ZIPs and 149/149 members rehash equal. Owner decided imported contents count when the ZIP matches by digest. Open: rebuild counts, and bytes of 12 HTTP 206 ZIPs unread. Body 5e9b5643 is an older edition of the 64404 transcript, the only wrongly excluded body; two later bodies list that URL. All branches: not merged; parser pins are recomputed once at integration; no backfill, lake write or full model run has happened.

**2026-11-02T10:24:10Z**

Owner decision 2026-11-02: restore body 5e9b5643 (older CHRG-119hhrg64404 edition) under the general rule, no exception. Data model §7.5: editions at one address are separate documents sharing version_keys, and the site lists all versions (ArchiveRows.tsx:41), not only the latest.

**2026-11-02T10:36:11Z**

Correction 2026-11-02 (lead), replacing the earlier note today: 5e9b5643 is not a distinct edition. Read in full and diffed: 5e9b5643, f332621e and c7768761 are byte-identical except a Cloudflare data-cfemail token that changes per fetch; their html fingerprints are equal (321e73cc), so §7.5 same_text merges them into one document showing the latest. Restoring it only moves first_captured to 2026-09-21. The owner's rule stands: identical versions merge and only the latest shows unless objectively different. The ZIP member b14d49d9 differs only by the decoded address DocumentsTI@mail.house.gov in place of '[email protected]', so its fingerprint differs and it would show as a second copy. Fix in the html reader: decode Cloudflare email spans before text and fingerprint (plan-g).
