---
id: ct-p3ff
status: open
deps: [cef-96wc]
links: []
created: 2026-11-01T20:08:13Z
type: task
priority: 3
assignee: mikewolfd
parent: ct-77zb
tags: [sql, cleanup]
---
# Delete the unused House select committee rule from meeting-records-resolved.sql

The hs* rule at model/sql/meeting-records-resolved.sql:105-106 matched 0 rows in publish_v21 meeting_records, because meeting_records.py already normalizes these codes. Replaces the sharing step of the rejected ct-kac4.

## Design

Re-run the zero-match query on the current selected meeting_records and retain it as the proof, then delete the rule. Changing model SQL changes file_hashes and input_digest, which forces a rebuild, so do this after the live switch. Keep missing_committee_keys as the real gate.

## Acceptance Criteria

- The query returns 0 on the current input.
- missing_committee_keys stays 0 on the next model run.

