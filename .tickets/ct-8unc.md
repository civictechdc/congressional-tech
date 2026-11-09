---
id: ct-8unc
status: in_progress
deps: []
links: []
created: 2026-11-09T00:31:06Z
type: bug
priority: 1
assignee: mikewolfd
tags: [daily, nightly, gate5, producer-records]
---
# Daily producer keeps its gate-5 records when the final head read fails

Nightly 20261108T193702Z (commit 12675ce0) ran produce_daily, appended archive_r1b.captures (8773215935267904969 -> 5555496601826602150) and archive_r1b.readings (1413391431006651405 -> 2552538235432233094), then the finally block's tables.resolve_tables failed with an iceberg REST catalog connect timeout (/v1/config, client error (Connect) operation timed out). _record_moved never ran, so the two moved heads have no producer record and every later nightly refuses with producer_unrecorded. Raw data is safe; the orchestrator wrote the two records by hand. produce_html_metadata and _activate_record_transition share the same finally shape.

## Design

Engine-first: the pinned engine reports retries=0 on resolve and exposes no catalog-connect retry knob in the job spec or client, so the Python caller retries. (1) _final_heads retries the idempotent post-append head read with waits of 10/30/90 s, each attempt in a sibling work dir; used by produce_daily, produce_html_metadata and _activate_record_transition. (2) produce_daily and produce_html_metadata durably write producer-owed.json (writer chain, initial heads, tables, catalog root, decided_at) before the first append and delete it once the records are written. On a persistent failure the raised error carries a note naming the file. (3) daily.complete_owed_records(path, engine=, producer_records=) re-reads heads, proves each moved head is the same table reached from its base by appends only, writes the records (write-once, idempotent) and deletes the file. Activation already has a durable journal and resume path, so it gets only the retry.

## Acceptance Criteria

Test: final head read fails once then succeeds -> records written, no owed file. Test: fails persistently -> error names the owed file, no records, later run refuses; complete_owed_records then writes records identical to the in-run ones and the next run chains from them. Existing producer record tests pass.

