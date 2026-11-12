---
id: ct-eppo
status: closed
deps: []
links: []
created: 2026-11-10T23:54:23Z
type: bug
priority: 3
assignee: mikewolfd
tags: [parser, witnesses, mods]
---
# The shared witness label reader misses three written-answer label shapes, so three printed answerers have no row

Found by the MODS witness-list work (branch claude/ct-mods-zs48-3aap, round 6, 2026-11-10). Three MODS lines print an answerer on a written-answer line but have had no row since the published release, because the label reader in packages/congress_api/src/congress_api/parsers/witness_names.py does not recognise the label: (1) CHRG-113hhrg86394 #8: FOOTNOTE and CONTENTS_LABEL match only number markers like \1\, not \*\; (2) CHRG-111hhrg62589 #5: UNMARKED_LABEL refuses a comma between the label and the name ('Answers to Submitted Questions, Mr. Jeff Hopkins'); (3) CHRG-110hhrg33608 #3: LABEL_WORDS has no singular 'Response to question submitted for the record by'. None prints an asker, so the MODS asker rule cannot reach them. The reader is shared by other producers, so a fix moves more than the MODS parser pin; measure which producers' fingerprints move and their row changes before deciding the release that carries it. The owner's rule for the result: an answerer with no testimony row of their own in the print is statement_for_record; one who testified keeps the type of their testimony row.

## Acceptance Criteria

The three lines each produce the answerer's row, typed by the owner's rule; a corpus survey of the three widened shapes shows every new match and no other row changes; each producer whose fingerprint moves is listed with its row delta; a raw-check plant for each shape is flagged.


## Notes

**2026-11-11T14:41:23Z**

validated 2026-11-11, left open: not fixed on main or on the MODS release branch claude/ct-mods-and-member-appearances (no diff to parsers/witness_names.py, no commit naming ct-eppo besides its filing 0bc32ccb).

**2026-11-12T15:50:00Z**

Wave 3 (`claude/ct-wave-3-parsers`): widened `witness_names.py` (`FOOTNOTE` / `CONTENTS_LABEL` `\*\`, `UNMARKED_LABEL` comma separator, singular `Response to question submitted for the record by`) and applied the owner's answerer typing rule in `appearance_records.py`. Full `35,020`-print MODS corpus survey matched the exact 3 rows (`CHRG-113hhrg86394 #8` Carmen Catizone, `CHRG-111hhrg62589 #5` Jeff Hopkins, `CHRG-110hhrg33608 #3` Jeanine Derby) with `0` unintended changes (`additions_vs_live == {'mods': 3}`, `removals == 0`); horizontal trace (`wave3_horizontal_slice_review.md` slice `H6`) further verified `ct-eppo` × `ct-sfra` promoting Carmen Catizone from `statement_for_record` in MODS lake to live witness (`None`) upon matching `STATEMENT OF CARMEN CATIZONE` in `CHRG-113hhrg86394.htm`. Ready for Merge Slot #1 + R2 backfill.
