---
id: ct-vq2a
status: closed
deps: []
links: [ct-94hw, ct-j9o7, ct-vrxc, ct-rvma, ct-flg9]
created: 2026-11-04T20:47:30Z
type: bug
priority: 1
assignee: mikewolfd
parent: ct-gi01
tags: [data-model, correctness, release-blocker]
---
# package_id follows the saved copy: 45 documents lose it and 28 get non-GovInfo filename ids

Nightly candidate ef4c1632 vs e4538f00: when a newer identical copy becomes the saved file (saved-files.sql, newest fetch wins), detail.package_id is re-derived from the new filename. 45 documents lose package_id; 28 gain ids that are not GovInfo packages (e.g. BILLS-117hr1833ih-Katko); 2 changes look right. Evidence: .cache/archive-release/nightly/20261104T174328Z/causes/evidence/05b-possible-defect-package-id.json.

## Acceptance Criteria

package_id derives from evidence that does not depend on which identical copy is saved (any capture of the same bytes, or the GovInfo package), and only GovInfo package ids pass. Fixture: identical bytes saved under a dated HHRG name then a plain name keep the same package_id.


## Notes

**2026-11-05T01:09:24Z**

Fixed on branch saved-copy-identity (72abdc8e, 4da601e2, 975c5250; not merged). Cause: document-normalized.sql fell back to the saved copy's source_annotations.package_id, which was the raw filename reading, so a newer identical copy (saved-files.sql: newest fetch wins) renamed or dropped the package. Fix: source-annotations-final.sql accepts a filename package only in GovInfo form (BILLS-{c}{type}{n}{version}, CHRG-{c}{h|s|j}hrg{n}, CRPT-{c}{h|s|e}rpt{n}, CPRT-{c}{H|S|J}PRT{n}, CDOC-{c}{h|s|t}doc{n}); -pt/-vol/-err/-ERRATA granules name their package; -Katko, -add2, -SUS, -Amdt and typeless BILLS-1171833ih name none. document-packages.sql: URL packages first (unchanged), then any copy's filename package, earliest fetched first. Hearing addenda (CHRG-*-add2) stay excluded from witness linking (document-witness-chrg-components.sql). Fixtures: phase1 source annotations, document_packages, and an end-to-end build (test_a_newer_identical_copy_never_renames_or_redates_the_document); the old model fails all three. Replay over the nightly's own evidence (.claude/worktrees/nightly/output/archive-model/evidence; script and outputs in .cache/archive-release/investigations/saved-copy-identity/): of the 75 package changes, 38 return to base, 34 become empty because the base value was not a GovInfo id either (typeless BILLS-1171833ih and markup names), 3 are corrections (BILLS-118hr7433ih, CHRG-119shrg61895 for its -add1, newly linked CHRG-119hhrg64573). Release-wide vs base: 20,701 lose a package that was not in GovInfo form (House member amendments BILLS-118-HR897-W000821-Amdt-1, -SUS suspension texts, typeless BILLS-NNNNih, CPRT-113-hprt-...); ArchiveDetail.tsx already hides these. 1,151 gain one from another copy, 336 change value. Open: 5 documents whose identical copies carry two different GovInfo-form bill names (BILLS-119hr2225ih vs BILLS-119hr225ih); earliest fetched wins and cannot tell which is right. Lanes: production-offline (full lane): exit 0; native-loopback (full lane): exit 0.

**2026-11-05T04:00:14Z**

Review change on saved-copy-identity, commit 7c703a7f (not merged; not rebased). document-filename-facts.sql ranks three tiers of name: House convention name (the reading's valid), then a committee site's '<sha256>.hhrg/hmkp/hmtg-...' copy, then a plain name. Then the earliest value. The hashed copy sits below the House name because in 8 documents it carries the posting day, one day before the hearing (Turley: hashed jturley-20160913 vs HHRG-114-SY00-Wstate-TurleyP-20160914 = meeting date); tying them would have moved those 8 off the hearing date. A date after its copy was captured, or outside its Congress's years, ranks below every plausible date (the truncated jbus-2070906 = 2070-09-06). Fixtures: unit cases for Webster (hashed beats plain), Bus (truncated hashed vs valid House name), upload-day, off-congress and future. End-to-end: Webster 2012-04-25 and Bus 2017-09-06. Plants: the 975c5250 ranking fails (Webster 2012-04-23, off-congress 2010-09-06); hashed tied with valid fails (upload-day 2016-09-13); dropping the Congress check fails (off-congress); dropping the capture check fails (future 2070-09-06). Replay vs the previous one (.cache/archive-release/investigations/saved-copy-identity/, previous saved as *-975c5250.*): 18 documents move, all to their base date, all won by a hashed hhrg copy with no House-named copy (Webster 1cbf3bd3 2012-04-23 to 2012-04-25; Sherlock and Thorning 2012-04-17 to 04-19; Shieber 03-26 to 03-29; Watkins 06-25 to 06-27). No document_date_source or Congress changes. Both jbus-2070906 documents stay 2017-09-06. Totals vs base now: 2,034 dates differ (was 2,052); the 18 nightly changes and the 1,215 are unchanged (8 and 1,211 back to base). production-offline (full lane): exit 0 (11,402 passed, peak 1.98 GiB).

**2026-11-05T15:45:07Z**

Published package identity is independent of which identical copy is saved. Invalid GovInfo forms/versions are rejected, authoritative GovInfo addresses retain precedence, and conflicting filename-only bill identities remain unresolved. Exact source controls and public reader assertions passed. Published and independently verified in e145d24c389e (2026-11-05), replacing e4538f00. Qualified source 7f9ebddd; publication source 0d517fd5. All three offline shards passed (11,497 tests), full native/storage lanes passed, all six data suites passed, and all 26 public assets match the approved bytes. Live checks passed 180 MCP assertions and 57 deployed-browser assertions. Release note: docs/releases/2026-11-05-e145d24c389e.md. Evidence: .cache/archive-release/handoffs/cursor-resume-20261105/publication-approved/.
