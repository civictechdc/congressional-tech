---
id: ct-w08x
status: open
deps: []
links: []
created: 2026-11-10T13:26:44Z
type: task
priority: 3
assignee: mikewolfd
tags: [model, determinism]
---
# Page-metadata picks can tie on a repeated pointer; only page-descriptions has a last key

From ct-n5ec (2026-11-10). model/sql/page-descriptions.sql orders its pick by format rank and JSON pointer; b441f29d added the value as the last key so input order cannot decide a tie. The same theoretical tie exists at model/sql/page-dates.sql:3, document-page-metadata-entries.sql:42 and document-page-metadata.sql:39,47 (only if one reading repeats a pointer for one body; pointers are indexed, so it may never occur). Nobody has counted repeats: page_metadata_values is step 181 and its result is not retained after a build. archive_format.py:168 orders every later reader by unique doc_key, so the published order is not at risk; the pick is.

## Acceptance Criteria

One query on a build's page_metadata_values counts (body_sha, field, path) groups with more than one row and the count is recorded. If it is not zero, the three other picks get the same last key with a test; if zero, an invariant asserts it stays zero.

