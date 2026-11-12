---
id: ct-uz8q
status: open
deps: []
links: [ct-gfo7, ct-sfra, ct-kw85]
created: 2026-11-12T00:18:56Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [congress_api, mods, witnesses]
---
# MODS round-9 accepted-defect parser lines and residual follow-ups (after ct-gfo7)

Carries forward the non-shipped MODS parser residuals after MODS round 9 (pin 704ba567) shipped in archive release 46ebbdf8dcaf (2026-11-11). Take byte-hashed appearance_records.py / witness_names.py changes together in a single intentional MODS bump:

1. Accepted-defect Member lines in model/jobs/release-causes/77673bfb8fcf-46ebbdf8dcaf.json (group 33, witnesses.parquet|changed witness_type):
   - Erik Paulsen (CHRG-113hhrg91127) and Cedric Richmond (CHRG-114hhrg96873): written statements currently typed member_appearance; should be member_statement.
   - Tim Walberg (CHRG-114hhrg94823): statement submitted on behalf of an organization currently typed member_appearance; should be record_material.
   - John Tierney (CHRG-112hhrg73706) and Luke Messer (CHRG-113hhrg89535): letters submitted for others that MODS round 9 types member_statement; should be record_material.
2. Shared label reader residuals from ct-gfo7 round 5 (parsers/witness_names.py): CHRG-110hhrg33608 #3, CHRG-111hhrg62589 #5, and CHRG-113hhrg86394 #8 print no asker (asterisk markers, comma after label, singular 'question submitted for the record by').
3. Minor print-entry residuals noted in ct-gfo7 rounds 1/3: CHRG-115shrg25981 #4 (Bill Cassidy run into Patty Murray's line), CHRG-112shrg25114 #3 (Boxer and Inhofe nameless heading row), and CHRG-106shrg66376 #25 (McConnell unresolved).
4. Print-attachment note from group 14 (meeting_coverage.parquet): 7 meetings whose Members sit beside an outside witness tied to no meeting on a linked print moved to unknown, package_witnesses_unattached (listed in vs-d505be8b.json / coverage-changes.csv).

## Acceptance Criteria

Items 1-3 each applied or explicitly declined in a single intentional MODS parser bump with raw-check plant verification; item 4 reconciled if unattached print-witness coverage is revisited.

