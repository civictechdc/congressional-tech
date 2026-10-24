---
id: ct-snzi
status: closed
deps: []
links: [ct-v9ua, ct-ugqq, ct-0odd, ct-syx8, ct-tw3r]
created: 2026-10-24T18:15:53Z
type: task
priority: 0
assignee: mikewolfd
parent: ct-v967
---
# Carry stored_sha256, refuse unqualified engines and remove delete_gzip (54a68ac7)

Done on Oct 24 in `54a68ac7`, pushed to main (audit raw risks 2, 3 and 5; plan P1, P2 and P3).

## Acceptance Criteria

- The capture schema carries `stored_sha256`, and the two places that inferred it now leave it null when unknown.
- Hosted setup refuses any engine revision other than `QUALIFIED_DOCSPEC_RUNTIME`.
- `migrate_pdf_bodies_to_uncompressed`'s `delete_gzip` option is removed.


## Notes

**2026-10-24T18:21:14Z**

Closed: done in `54a68ac7` (on main). Checks run then: capture workflow offline suites (6207 + 84 passed); the affected raw, edge, recovery and e2e files (175 passed); engine-backed raw storage tests (38 passed); the hosted capture validation passed. Evidence: `docs/reviews/2026-10-24-ticket-audit/README.md`, "Actions taken on Oct 24".
