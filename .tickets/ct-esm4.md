---
id: ct-esm4
status: closed
deps: [ct-fqgf, ct-vxzu]
links: [ct-n3qy, ct-vxzu, ct-ma8a, ct-fqgf, ct-vd5b, ct-piku, ct-bpyj, ct-r46l]
created: 2026-10-19T17:00:41Z
type: task
priority: 2
assignee: mikewolfd
tags: [script-restructure]
---
# Package corpus recovery behind executing-file pins

Architecture review of the top-level scripts/ restructure returned RECONSIDER. This ticket describes the reshape, not the blocked original plan. Implementation agent 338f11a1-e496-4c63-b886-17efe958ffec is applying the reshape now.

Dispatchers pin the package files that execute, not only shims. Leave reconcile_corpus_recovery_bodies.py CLI in scripts/ with ROOT equal to the checkout root. Web Harvest scripts stay in scripts/. classify_recovery_html_transcripts must remain importable by webharvest_recovery.py.

This does not close ct-piku or ct-bpyj. Those links are related-but-not-closing. ct-piku still owns declared-runtime import ownership. ct-bpyj still owns one accepted viewer plan for local and cloud publication.

Depends on the caller-owned seal comparison and the plain lost-ack helper. Finish those before this package is done.

## Acceptance Criteria

- Dispatchers pin the package files that execute, not only shims.
- scripts/reconcile_corpus_recovery_bodies.py remains a CLI in scripts/, and ROOT is the checkout root.
- Web Harvest scripts stay in scripts/.
- webharvest_recovery.py can still import classify_recovery_html_transcripts.
- ct-piku and ct-bpyj are still open after this ticket closes.
- The caller-owned seal comparison and the plain lost-ack helper are done first.


## Notes

**2026-10-19T18:10:39Z**

94d8946036f08223cea9cf2ee3d93ade9b38e4c6 Package the corpus recovery library and keep its commands in scripts.
d72aca7aa167dda77e647fccf27533e31add5407 Pin the recovery modules that publication and import actually run.
