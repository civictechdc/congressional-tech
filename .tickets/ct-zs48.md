---
id: ct-zs48
status: in_progress
deps: []
links: [ct-79j1, ct-3aap, ct-gfo7]
created: 2026-11-08T20:05:51Z
type: bug
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [congress_api, mods, witnesses]
---
# Split Norton and Lipinski's combined MODS witness line in CHRG-114hhrg93258

Found by the ct-79j1 survey (2026-11-08): witness 10 of CHRG-114hhrg93258 joins 'Hon. Eleanor Holmes Norton …' and 'Hon. Daniel Lipinski …' on one MODS line. Apply the same reviewed joined-line split as ct-79j1 (MODS_JOINED_LINES keyed by package, witness position and line SHA-256, second part at mods:witness[10]/part[2]), with a focused test on the real bytes, then re-run the MODS generation through the reviewed activation path.


## Notes

**2026-11-09T18:52:18Z**

Built on claude/ct-mods-zs48-3aap with ct-3aap (one MODS bump 8a0023a9 -> 94752714; not regenerated or activated). MODS_JOINED_LINES binds CHRG-114hhrg93258 witness 10 (line sha256 150246912b93..., separator '.. '). Raw body b7222c47...: the line sits under 'Responses to questions for the record from the following Representatives and Delegate'; Norton (Delegate, DC) keeps mods:witness[10] with position 'of the District of Columbia' and no organization; Lipinski (Representative, IL) reads at mods:witness[10]/part[2], display order 10. Neither is a WITNESS congMember (Lipinski is COMMMEMBER L000563; Norton absent), so neither links to a bioguide, like Graves..DeFazio above them. Measured on all 35,020 MODS originals against requalify-525d20ba/appearance-generations.parquet: 1 added, Norton's position/organization trimmed, nothing else for this ticket. Raw check split judgment and split-untrimmed plant: mods-zs48-3aap-20261109 scratch (worktree .cache).

**2026-11-09T20:05:39Z**

Review follow-up (owner 2026-11-09, fold in): question-for-the-record lists are record material, not witnesses. Survey of all 35,020 MODS originals: 22 headings that name their asker after a colon, 31 Member lines under them, plus 18 paged 'Senator X......23,' asker lines in Senate prints. Rule (mods_entry_kind owns all record typing): a heading 'Responses/Answers to ... questions ...:' or 'Questions and Answers ... from:' whose tail is empty, one asker, or a list of Senators is kept as a record_material row read for its asker (17 headings were dropped as labels and are restored, including Shuster at CHRG-114hhrg93258 mods:witness[2]; 5 kept with garbage names are renamed to the asker); Member-only lines after it are record_material until a line that is not; a titled paged asker line is record_material anywhere. Headings run into another entry keep their reading (listed in the report). Reviewed MODS_RECORD_ENTRIES: CHRG-114hhrg94806 9-10 (Carson, DeFazio after Feinberg, no heading) and CHRG-115shrg25981 4 (Patty Murray). Norton and Lipinski are now record_material, display orders 10 and 11. MODS pin ee3f2c6e (pre-an6o).

**2026-11-09T20:25:59Z**

Rebased onto main after ct-an6o (16084de5): MODS publishes its new import-closure fingerprint 6a4a9765 with no map entry; the stale 8a34087e->8a0023a9 entry is removed. Final measurement (m5, extraction unchanged by the rebase, uv.lock identical): 169 occurrence diffs in 52 packages, 108,708 -> 108,726 MODS occurrences, none removed. Evidence: .cache/archive-release/implementation/mods-zs48-3aap-20261109/ (m5/measure.json, m5/changes-by-cause.json, raw-check-final.json, raw-check-accept.json, plants). Not regenerated or activated.

**2026-11-09T21:51:59Z**

Review r3 fixes (pin 0b58c1a2): _MODS_PAGED_ASKERS made possessive (exponential backtracking on long failing lines of paged askers; 0.05 ms at 200 groups; old and new agree on all 108,896 corpus witness lines, 19 matches); the question-heading reading now runs once per line. Seven Senate VA askers printed 'Hon. X......pages Hon. Y' after a witness, and CHRG-113shrg80510's 'Response to request arising during the hearing by: Hon. Richard Burr', are sha-bound record_material MODS_RECORD_ENTRIES (a shape rule would mistype real witnesses printed the same way); the second named Member of each line stays only in the raw line. CHRG-112shrg25114 #3 is a reviewed joined line (MODS_JOINED_LINES now holds a separator pattern): the heading naming Boxer and Inhofe is a nameless record row and witness Amy W. Larson reads at /part[2]. Against m5: these 8 lines change 10 occurrences (Larson's line yields 2, and Williams' display order moves 3->5). Left as the review noted, no change: CHRG-110shrg75166 #3 (FTC) and CHRG-114hhrg93962 #11 (National Commission on Hunger) are debatable statement_for_record rows (the witnesses' own body's document); the review's re-run, state survey and plant confirmation need no action. Evidence: .cache/archive-release/implementation/mods-zs48-3aap-20261109/fix-r3/.

**2026-11-09T23:08:29Z**

Review follow-ups filed as ct-gfo7 (seven residual items, one MODS bump). Still to do before activation: (1) the previous-segment plant in scripts/measure/mods_name_fields_raw_check.py was run by the rule's author only (evidence fix-r3-n13/README.txt); a reviewer other than the author must confirm it. (2) Two product calls go to the owner: the second Member on five joined asker lines (Burris, Moran, Begich, Manchin) is in no field, and the organization text is dropped on the 16 reviewed title rows; the raw record keeps both. No full lane has run on this branch yet; it waits for the nightly to finish.

**2026-11-10T12:21:00Z**

Owner decision 2026-11-10 (joint askers), MODS pin 0b58c1a2 -> e39e365b: the five lines naming two Members who asked jointly publish both, the second at <locator>/part[2], record_material, through MODS_RECORD_ENTRIES (an entry may now hold two names): CHRG-111shrg47763 #2 (Tester, Burris), CHRG-111shrg64440 #2 (Tester, Begich), CHRG-115shrg24586 #3 and #4 (Tester, Moran; #4 is the heading of ct-gfo7 item 2), CHRG-115shrg34881 #5 (Brown, Manchin). No schema change: /part[2] is the locator Lipinski and Larson already use. Measured (m8, all 35,020 originals): against the 0b58c1a2 candidate 39 occurrence diffs in 17 prints, none removed: 5 second Members added, 16 title rows regain organization, Shulkin's fields, the #4 heading renamed, 16 display-order shifts behind the added rows; nothing else. Against the published generation (pin 8a0023a9): 202 occurrence diffs in 59 prints, 177 changed, 25 added, 0 removed; MODS occurrences 108,708 -> 108,733. Raw check on m8, no accepts: 43 flags (65 on m7); four of the five second Members pass its split judgment unaided; new flags only on CHRG-115shrg24586 #4 (words_lost, split_unsupported). The retained accept list is stale (40 stale, 18 occurrences to re-read: the 16 titles and both #4 rows) and must be re-made by a reviewer. Still to do before activation: a reviewer other than the author re-makes the accepts and confirms the plants (all six were re-run by the author on m8 only); full lanes; the reading-version drift decision for versions.py. Evidence: .cache/archive-release/investigations/mods-rebase-20261110/ (m8/, raw-check-m8-*.json, mr-*.py).

**2026-11-10T13:27:10Z**

2026-11-10 (session congress-1): branch claude/ct-mods-zs48-3aap rebased onto main (08413328), then c9ca5b14 added both joint askers and the organization text on the 16 reviewed titles (owner decisions: 'Show both senators', 'Title plus the organization', MODS branch 'in the next release'). Independent review (opus xhigh): confirmed with corrections; recount exact (202 rows in 59 prints: 177 changed, 25 added, 0 removed); all 18 stale-accept rows read from raw lines are right. Corrections in progress on the branch: every multi-Member asker line in the 35,020 originals (CHRG-115shrg35700 #6, CHRG-111shrg21635 #7, 25981 #4, 25114 #3 were missed), five raw-check gaps with built-in plants, and three further owner decisions from ct-gfo7 (LoBiondo line shown with both names; FTC and Hunger Commission rows become record material; build the Member Day rule now). Still owed before activation: a second independent confirmation of the new plants, the reading-version drift decision, full lanes, regenerating the appearance table at the new pin.

**2026-11-10T15:41:13Z**

2026-11-10 (session congress-1): second independent review of tip 35e24dae: confirmed with corrections (93 of 96 accept candidates signed, 3 rejected; nine more multi-Member lines still wrong; about 70 Members on question lines have no row). Owner decisions the same day: 'Members shouldn't be witnesses unless they are not in an official capacity'; build one asker rule keyed on Member identity now, in this branch. The reading-version equivalence for the versions.py edit is recorded on the branch (374b9f56). A builder is on the asker rule (round 3); a third reviewer follows. Sitting Members at ordinary hearings are ct-kw85, not this ticket.

**2026-11-10T13:46:44Z**

Round 2 (2026-11-10, owner decision 'show both senators' applied to every line of the kind), MODS pin e39e365b -> e599dff6 (one bump with ct-gfo7 items 3-4; intermediate commit 7850334a at eaae156d). A survey of all 35,020 MODS originals found 22 question lines naming more than one Member as askers; 6 already named each, 16 now do. Read by the question rule (regular shape, right on every such line in the corpus): CHRG-111shrg21635 #6 and #7, CHRG-114shrg23001 #2 (ten Senators), CHRG-115shrg31195 #2 (five), CHRG-115shrg35700 #6 (Sanders, Harris), CHRG-112shrg25114 #3 (Boxer, Inhofe; Larson stays /part[2], Inhofe /part[3]). Reviewed entries: CHRG-115shrg33409 #2/4/6/8, CHRG-115shrg25981 #4 (Murray, Cassidy), CHRG-116shrg40570 #2 and CHRG-112shrg86775 #8 (headings that had published as a witness name), CHRG-115hhrg25242 #2 (LoBiondo, Mitchell), and 'askers' entries appending askers after a published witness row (CHRG-106shrg66382 #9, CHRG-107shrg83717 #6). MODS_TITLE_RECORD_ENTRIES folded into the entry's third value ('document'); the 16 title rows are identical to m8. Measured (round-2/m10): vs c9ca5b14 106 occurrence diffs in 16 prints, 66 changed, 40 added, 0 removed; vs published 8a0023a9 292 in 66 prints, 227 changed, 65 added, 0 removed; MODS occurrences 108,733 -> 108,773. Evidence: .cache/archive-release/investigations/mods-rebase-20261110/round-2/.

**2026-11-10T16:55:15Z**

Round 3 (2026-11-10): the asker rule replaces the joint-asker entries; MODS pin e599dff6 -> 63715237. Details and measurements in ct-gfo7's round-3 note.
