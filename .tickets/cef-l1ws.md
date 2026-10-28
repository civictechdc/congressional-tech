---
id: cef-l1ws
status: closed
deps: []
links: []
created: 2026-10-28T07:18:34Z
type: bug
priority: 1
assignee: mikewolfd
---
# Keep non-record provenance in publication identity without model reads

The full provenance inventory includes the retained accepted.json backup, which DM5.3 explicitly excludes from model records. The controller must pin all opaque ETags while selecting exactly the recognized direct JSONL record inputs; omitted true records must still refuse. Prove no backup GET or parse and stale backup metadata refusal with fake storage and the actual native model.


## Notes

**2026-10-28T07:24:55Z**

Contracts 7b0b636e and d63de700 reproduced the native publication and three metadata admission failures. Binding b7979eda passes 64 controller/model/publisher focused checks in 32.46s on qualified 71cc6eb. Static independent CODE review APPROVE with no findings (cx_fresh_provenance_review/review.md). Full provenance metadata and opaque ETags remain in identity; model reads exactly recognized records, never the accepted.json backup. No live effect.
