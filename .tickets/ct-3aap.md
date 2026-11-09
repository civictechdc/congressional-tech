---
id: ct-3aap
status: open
deps: []
links: [ct-rg34]
created: 2026-11-09T03:09:09Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [congress_api, mods, witnesses]
---
# Type organization-only MODS record lines as record entries

Found by the ct-rg34 review (2026-11-08). Most MODS lines that ct-rg34 reads as an organization alone (name NULL, text in organization) are record entries, not witnesses: 'American College of Cardiology, Bethesda, MD, statement', 'National Restaurant Association, letter, dated Sept. 8, 2014', '..., prepared statement'. mods_entry_kind types them as witnesses (witness_type NULL) because the record markers it reads open the line or follow a Member's name. Decide whether an organization-only line ending in a document word (statement, prepared statement, letter, memorandum, article, paper, report, attachment) is statement_for_record or record_material, measure it on all MODS originals, and ride the next MODS parser bump. ct-rg34 did not change witness_type.

