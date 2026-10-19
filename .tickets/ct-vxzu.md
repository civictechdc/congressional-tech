---
id: ct-vxzu
status: closed
deps: []
links: [ct-esm4, ct-n3qy, ct-ma8a, ct-fqgf, ct-vd5b, ct-2uwd, ct-r46l]
created: 2026-10-19T17:00:40Z
type: task
priority: 2
assignee: mikewolfd
tags: [script-restructure]
---
# Share exact-byte lost-ack reconcile for plain callers

Architecture review of the top-level scripts/ restructure returned RECONSIDER. This ticket describes the reshape, not the blocked original plan. Implementation agent 338f11a1-e496-4c63-b886-17efe958ffec is applying the reshape now.

Add a shared exact-byte reconcile function for import_corpus_recovery_batch.checked_put and a plain publish_mappings client. Do not fold that helper into GuardedPublicationClient.put_object. When the client returns _verified_transfer, publish_mappings consumes that receipt and does not read the body again.

ct-2uwd already says publish_mappings should consume the guarded readback. Link this ticket to ct-2uwd. Do not close ct-2uwd.

## Acceptance Criteria

- A shared exact-byte reconcile function is used by import_corpus_recovery_batch.checked_put and a plain publish_mappings client only.
- GuardedPublicationClient.put_object does not gain this helper.
- When the client returns _verified_transfer, publish_mappings consumes that receipt and does not read the body again.
- ct-2uwd remains open.


## Notes

**2026-10-19T18:10:39Z**

1f2c45548358976f4cbfc0ecb51e03251cc9b886 Keep guarded writes off the plain lost-ack helper.
