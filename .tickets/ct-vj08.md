---
id: ct-vj08
status: closed
deps: []
links: []
created: 2026-11-11T10:58:10Z
type: bug
priority: 3
assignee: mikewolfd
tags: [parser, witnesses, mods]
---
# MODS names: lower-case surname entries lose the given name, 'the Honorable' left in names, and more honorific abbreviations read as sentence breaks

Found by the seventh independent review of the MODS witness-list branch (2026-11-11, .cache/archive-release/investigations/mods-rebase-20261110/review-6/r7-light.txt). Pre-existing on the live site and unchanged by that branch: 161 published MODS rows have names starting in lower case; about 36 lower-case-surname entries (e.g. 'van Welie') have lost the given name, and about 25 carry 'the Honorable' in the name. Latent in the prose shape rule (round 9 made hon, mrs, messrs, sen, rep, gen, col, capt, sgt, prof, esq, rev, adm, cmdr not count as sentence breaks): 'Gov.', 'Maj.', 'Amb.', 'Sec.', 'Inc.' and 'Corp.' still do; no current line is affected.

## Acceptance Criteria

Every lower-case-surname entry keeps its given name; no published name begins with 'the Honorable'; the abbreviation list covers the six; a raw-check plant for each shape is flagged; removals 0 against the live generation.

## Notes

**2026-11-12T15:57:00Z**

Wave 3 (`claude/ct-wave-3-parsers`): joined lowercase surname particles (`van`, `von`, `de`, `den`, `del`, `der`, `della`, `di`, `da`, `du`, `la`, `le`, `ten`, `ter`, `al`) to given names, stripped lowercase `the Honorable` into `honorific`, and added `Gov.`, `Maj.`, `Amb.`, `Sec.`, `Inc.`, `Corp.` to `_MODS_PROSE_ABBREV`. Full `35,020`-print MODS corpus: lowercase-initial names dropped `161 -> 94` (remaining 94 are legitimate lowercase particles/prefixes or non-inverted prose, `0` `lowercase_surname_unjoined`), leading `the Honorable` dropped `25 -> 4` (`0` `honorific_in_name`; the 4 remaining are non-honorific institutional phrases), `removals == 0`, plants caught; verified end-to-end through Playwright DOM (`wave3_horizontal_slice_review.md` slice `H7` Mark de Bernardo). Ready for Merge Slot #2 + R2 backfill.


