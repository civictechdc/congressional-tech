---
id: ct-zs48
status: in_progress
deps: []
links: [ct-79j1, ct-3aap]
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

**2026-11-10T13:27:10Z**

2026-11-10 (session congress-1): branch claude/ct-mods-zs48-3aap rebased onto main (08413328), then c9ca5b14 added both joint askers and the organization text on the 16 reviewed titles (owner decisions: 'Show both senators', 'Title plus the organization', MODS branch 'in the next release'). Independent review (opus xhigh): confirmed with corrections; recount exact (202 rows in 59 prints: 177 changed, 25 added, 0 removed); all 18 stale-accept rows read from raw lines are right. Corrections in progress on the branch: every multi-Member asker line in the 35,020 originals (CHRG-115shrg35700 #6, CHRG-111shrg21635 #7, 25981 #4, 25114 #3 were missed), five raw-check gaps with built-in plants, and three further owner decisions from ct-gfo7 (LoBiondo line shown with both names; FTC and Hunger Commission rows become record material; build the Member Day rule now). Still owed before activation: a second independent confirmation of the new plants, the reading-version drift decision, full lanes, regenerating the appearance table at the new pin.

**2026-11-10T15:41:13Z**

2026-11-10 (session congress-1): second independent review of tip 35e24dae: confirmed with corrections (93 of 96 accept candidates signed, 3 rejected; nine more multi-Member lines still wrong; about 70 Members on question lines have no row). Owner decisions the same day: 'Members shouldn't be witnesses unless they are not in an official capacity'; build one asker rule keyed on Member identity now, in this branch. The reading-version equivalence for the versions.py edit is recorded on the branch (374b9f56). A builder is on the asker rule (round 3); a third reviewer follows. Sitting Members at ordinary hearings are ct-kw85, not this ticket.
