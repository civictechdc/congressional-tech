---
id: ct-n5ec
status: in_progress
deps: []
links: []
created: 2026-11-10T00:20:04Z
type: bug
priority: 0
assignee: mikewolfd
tags: [nightly, model, engine]
---
# Nightly base_normalized exhausts the query pool: four trailing LEFT JOINs build on the document row; engine slice guard misses list columns

Nightly 20261109T224443 failed at model step 172 base_normalized: charged 9.26 GiB of a 12 GiB pool for about 1.2 GiB real. Findings: .cache/archive-release/investigations/nightly-20261109T224443-base-normalized-memory/findings.md. Owner chose (2026-11-10, questions tool) SQL and engine together: move the four trailing LEFT JOINs in model/sql/document-normalized.sql into the RIGHT JOIN nest and guard it in the join audit test; fix docspec-rs sliced_batch_bytes for nested columns, rebuild and re-pin. Also decide and record whether the fallback to the remote runtime limits (24 GiB, above the 14 GB watchdog) is intended: publish-model.json names a runtime file that does not exist.

## Acceptance Criteria

Join audit test covers base_normalized. Old and new step output byte-identical ordered by doc_key. Engine test shows a sliced List build input is no longer charged per slice. Re-pinned engine passes the full lanes. A nightly passes base_normalized.

