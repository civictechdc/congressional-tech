---
id: ct-rg34
status: in_progress
deps: []
links: [ct-79j1, ct-3aap]
created: 2026-11-09T00:27:36Z
type: bug
priority: 2
assignee: mikewolfd
parent: ct-77zb
tags: [congress_api, mods, witnesses]
---
# Read organization-first MODS witness lines: organization out of name

About 1,200 current mods witness rows in release 630164505301 carry an organization in name (U.S. Department of Veterans Affairs 158, American Legion 94, Disabled American Veterans 75, U.S. General Accounting Office 68, U.S. Department of the Treasury 53, U.S. Government Accountability Office 51). GPO writes these lines organization first ('Vietnam Veterans of America, Richard F. Weidman, Executive Director ...'), so the name parser takes the organization as the name and the person as the position. Owner approved 'file a ticket and fix now' on 2026-11-08. Policy: drop nothing. A line that names a person after the organization reads that person as name; an organization-only line keeps its row with name NULL and the text in organization. Shares the ct-79j1 mods parser_version bump and its later regeneration (branch from claude/ct-79j1-abbott). Measure before/after on all MODS originals the release used, with a false-positive check that no person's name moves, and a raw check under scripts/measure/.


## Notes

**2026-11-09T00:56:51Z**

2026-11-08 scope addition approved by the owner (questions tool, 'Add to the MODS fix'): also fix surname-first lines whose surname is more than one word ('Herrera Beutler, Hon. Jaime, a Representative ...' read as name 'Herrera Beutler', position 'Hon. Jaime'), and the 'Page <Surname>, Mr. <Given>' contents-heading variant. Field split only; linking Members without bioguide_id stays with later entity work. All three MODS fixes (ct-79j1 Abbott, organization names, surname split) share one mods parser_version bump and one regeneration.

**2026-11-09T01:40:05Z**

2026-11-08 fix on claude/ct-rg34-mods-org-names (from claude/ct-79j1-abbott @ 9a33823c). MODS pin 05545523 -> 0e1a2ca1 (shared with ct-79j1). Re-read all 35,020 MODS originals against the ct-79j1 generation: 2,809 occurrences change name/position/organization only (none added or removed; no witness_type, on_behalf_of, display order or bioguide change): 2,513 person read after the organization, 79 organization-only (name NULL, text in organization), 217 multi-word or 'Page' surname joined. Reaches 2,808 rows of release 630164505301 (2,801 current). 4 reviewed MODS_PERSON_FIELDS entries that nulled position and organization on org-first lines are removed (they would now drop the organization). Human-reviewed boundaries fixture: 77 of 86 lines change, all 77 agree with the reviewed name. Raw check scripts/measure/mods_name_fields_raw_check.py passes with 236 read-and-accepted flags; both planted cases flagged. Evidence: .cache/archive-release/implementation/mods-org-names-20261108/. Regeneration and activation follow the ct-79j1 runbook (updated). ct-zs48 (Norton/Lipinski joined line) does not fall out of this code; left open.

**2026-11-09T03:37:39Z**

2026-11-08 follow-up (independent review of ebba423c + owner decisions): rule now abstains when unsure (several unmarked candidates, an unreadable marked person, a state, a later segment that could open a name, >3-word unmarked names); Blunt Rochester fix (surname must open the line as printed); 64 reviewed MODS_PERSON_FIELDS entries deleted and 4 edited so organization is no longer blanked on lines the rule reads (owner: remove them); docstring says what organization means; site labels a nameless witness with its organization (owner). MODS pin 0e1a2ca1 -> 54aa28e3. Re-measured on all 35,020 MODS originals: 2,739 changed (2,398 person after organization, 213 surname joined, 60 organization only, 68 organization restored), none added/removed. Raw check adds name_not_person, row-by-row accepts keyed on the new value (250), and a third planted case; passes, all three plants flag. Record-entry typing of organization-only rows filed as ct-3aap.
