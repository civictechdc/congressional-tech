---
id: ct-w08x
status: closed
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


## Notes

**2026-11-11T14:43:58Z**

validated 2026-11-11, left open: the one counting query has not been run. page_metadata_values is still not retained after a build (the 77673bfb8fcf clone's archive-model/evidence has no such file), so it needs a model-only build with that step retained, or a query job through dev.py query on a build's workspace.

**2026-11-12T03:04:00Z**

Counted `(saved_body, field, path)` groups across all 55,114 published `page_metadata` entries (`55,096` distinct `(saved_body, field, path, value, format)` facts) in `46ebbdf8dcaf` (`release-20261111-mods/candidate-at-gate/archive-release/detail.parquet`): **0** repeated `(body_sha, field, path)` groups (`html_metadata.page_facts` constructs JSON Pointers from unique dict keys and `enumerate` indices). Added `page_metadata_pointer_repeats` (`duplicate_page_metadata_pointers == 0`) to `model_invariants` so every release build asserts the count stays zero on `page_metadata_values`, and added deterministic value/format last-key tie-breakers to `model/sql/page-dates.sql`, `model/sql/document-page-metadata-entries.sql`, and `model/sql/document-page-metadata.sql` with order-independence and invariant tests in `test_page_metadata_model.py`.
