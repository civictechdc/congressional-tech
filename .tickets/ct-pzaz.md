---
id: ct-pzaz
status: open
deps: []
links: []
created: 2026-11-17T20:17:27Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-ihe7
tags: [docmeta]
---
# DocMeta rules carry their own committee-code and filename tables beside house_naming

The moved rules (provenance_rules_v5.py HOUSE_CLERK_2LETTER_TO_CODE and DOMAIN_TO_COMMITTEE_CODE, pythonic_v6.py HOUSE_SELECT_2LETTER_EXTRA_V6, relational_rules_v6.py committee_code_to_canonical_v6, slug parsing in expanded_rules_v5.py) overlap packages/house-naming and normalize_house_committee_code in meeting_records.py, which AGENTS.md names as the single owner of House select-committee code normalization. Moved as is in ct-ihe7 because folding them changes rule output. Also three copies of the DocMeta data-folder default (an absolute path) in gold.py, pythonic_v6.py and relational_rules_v6.py.

## Acceptance Criteria

Measure where the DocMeta tables and house_naming disagree on the release's filenames and committee codes; one owner per table; the no-model comparison in .cache/archive-release/docmeta-move-20261117 shows which outputs move.

