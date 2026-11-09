---
id: ct-3aap
status: in_progress
deps: []
links: [ct-rg34, ct-zs48]
created: 2026-11-09T03:09:09Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [congress_api, mods, witnesses]
---
# Type organization-only MODS record lines as record entries

Found by the ct-rg34 review (2026-11-08). Most MODS lines that ct-rg34 reads as an organization alone (name NULL, text in organization) are record entries, not witnesses: 'American College of Cardiology, Bethesda, MD, statement', 'National Restaurant Association, letter, dated Sept. 8, 2014', '..., prepared statement'. mods_entry_kind types them as witnesses (witness_type NULL) because the record markers it reads open the line or follow a Member's name. Decide whether an organization-only line ending in a document word (statement, prepared statement, letter, memorandum, article, paper, report, attachment) is statement_for_record or record_material, measure it on all MODS originals, and ride the next MODS parser bump. ct-rg34 did not change witness_type.


## Notes

**2026-11-09T18:52:18Z**

Decision: an organization-only line (no name read, organization set) ending in ', [prepared|submitted] statement|letter|memorandum|article|paper|report[s][ and attachment(s)][, dated ...]' is statement_for_record (the type mods_entry_kind gives other organizations' letters and statements; the model already treats all three record types alike). Only organization-only lines: a person's line ending the same way stays the witness (D4 gate). Built on claude/ct-mods-zs48-3aap with ct-zs48. Measured on all 35,020 MODS originals: 37 witness_type changes None -> statement_for_record, nothing else. The live generation has 60 organization-only rows, not 79; the other 23 stay untyped: 10 are document titles without an ending document word (raw check lists them as untyped_record, e.g. 'Summary of Goals and Projects, December 20, 2010', 'Department of Veterans Affairs, example of letter sent to Veterans', 'Prepared Statement of the National Park Service, on H.R. 586'), the rest organizations or headings (e.g. 'Blinded Veterans Association, New York, Inc', 'Gyres Institute, Leap Lab'). Raw check type judgment and typed-organization plant added.

**2026-11-09T20:05:39Z**

Review follow-up (owner 2026-11-09, reviewed list): 16 document titles typed record_material through sha-bound MODS_RECORD_ENTRIES (AAR 'Calls for...', GAO 'Public Safety Communications...', both Project Labor Agreements, 'Report of the National Surface Transportation ... Commission', 'Summary of Goals and Projects', SEJ letter, etc.); the existing reviewed mechanism keeps no fields, so their text moves out of organization (raw MODS keeps it). The two 'Prepared Statement of ........ 300,' dot-leader leftovers (CHRG-116shrg39734 4, CHRG-115shrg26915 5) stay visible as nameless record_material rows. The trailing-document rule moved into mods_entry_kind (organization passed in); its 37 rows are unchanged.

**2026-11-09T20:25:59Z**

Rebased with ct-zs48 onto main after ct-an6o; final MODS pin 6a4a9765. Reviewed list now 16 titles + 4 dot-leader 'Prepared statement......NN,' leftovers (CHRG-116shrg39734 4, CHRG-115shrg26915 5, CHRG-106shrg66381 26, CHRG-110shrg55921 3) + 3 headingless askers.

**2026-11-10T13:27:10Z**

2026-11-10 (session congress-1): see ct-zs48 for the branch state. The 16 reviewed title rows keep their line in organization (no title field exists; three name no organization). Owner decision 2026-11-10: the FTC and National Commission on Hunger rows become record_material.
