---
id: ct-p3ff
status: closed
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


## Notes

**2026-11-02T14:35:28Z**

2026-11-02 (lead): folded into r1b-f: rule deleted (0 of 18,183 Congress.gov and 6,287 House XML codes matched); 0 committee keys missing.

**2026-11-02T14:46:34Z**

2026-11-02 (lead): the leftover hszt00 rule was removed too (27c6ad6c); the SQL now only lowercases committee codes, and a test fails if any model SQL rewrites a committee code. missing_committee_keys = 0; htzt00 is still on 3 meetings via the parser.

**2026-11-03T22:53:35Z**

Closed 2026-11-03 after full D1-D4 + model build, Gates 1-5 pass (model/jobs/release-causes/448651e72083-e4538f0064e1.json, docs/releases/2026-11-03-e4538f0064e1.md), Basin import with producer proofs, full production-offline lane exit 0 (10,967 passed on release-train), and live publication of release e4538f0064e18168089a77891c93a16e175af18ed75eb7a3ac8039aa1a8db9fd (replacing 448651e720833d42d565ead119f59b893936626f680fdae4d13b6297e296c419) verified via contract:archive, live canary:archive, and congressional-explorer-mcp.
