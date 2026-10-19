---
id: ct-r46l
status: closed
deps: [ct-vxzu, ct-fqgf, ct-vd5b, ct-ma8a, ct-esm4, ct-n3qy]
links: [ct-esm4, ct-n3qy, ct-vxzu, ct-ma8a, ct-fqgf, ct-vd5b]
created: 2026-10-19T17:00:41Z
type: task
priority: 2
assignee: mikewolfd
tags: [script-restructure, wont-do]
---
# Do not revive the blocked scripts reshape

Architecture review of the six-task scripts/ restructure returned RECONSIDER. This ticket records the blocked original shape so it is not redone.

Do not make sealed_inputs the only reader of the five batch files, and do not replace viewer_release_identity.py with a shim that imports an installed package.

The five batch files sealed_inputs reads are manifest.json, prepared-source-records.json, source-record-preparation.json, zip-receipts.json, and bodies.json. Other callers keep their own reads.

tk has no cancelled status and no superseded-by link type. closed means will not do. tk dep is the blocked-by relationship: this ticket depends on the reshape tickets that replace this plan. Symmetric tk link records the same association on both sides, because a closed dependent does not appear in a ticket's Blocking list. Closing the reshape tickets does not authorize this work. Do not reopen this ticket.

## Acceptance Criteria

- sealed_inputs is not made the only reader of the five batch files.
- viewer_release_identity.py is not replaced by a shim that imports an installed package.
- This ticket stays closed. Resolved dependencies are not permission to reopen it.

