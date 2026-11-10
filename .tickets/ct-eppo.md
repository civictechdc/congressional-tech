---
id: ct-eppo
status: open
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

