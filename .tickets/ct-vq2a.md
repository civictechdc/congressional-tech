---
id: ct-vq2a
status: open
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
