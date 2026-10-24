---
id: ct-1l1h
status: open
deps: []
links: [ct-syx8]
created: 2026-10-24T18:15:53Z
type: task
priority: 0
assignee: mikewolfd
parent: ct-v967
---
# Turn on R2 bucket lock rules for receipts/, bodies/ and provenance/

Owner action (plan P4, owner decision 4). Add R2 bucket lock rules with indefinite retention on the `receipts/`, `bodies/` and `provenance/` prefixes of `congressional-tech-raw`. This is the platform barrier behind WS2's code key policy.

## Acceptance Criteria

- Lock rules exist for all three prefixes, with indefinite retention.
- The rules are read back (API or dashboard) and recorded in this ticket.
- After any later infra change, R2 check 4 reads the rules back again.

