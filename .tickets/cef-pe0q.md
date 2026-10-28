---
id: cef-pe0q
status: in_progress
deps: []
links: []
created: 2026-10-28T04:31:38Z
type: task
priority: 1
assignee: mikewolfd
---
# Publish native archive releases through one guarded controller

Bind the existing release model, native create-only transfers, receipt-key pins and site probes into one publisher. Preserve early skips, immutable assets/input records, strict 412 readback and conditional pointer writes; publish never deletes. Test locally with real model artifacts and fake external storage/probes; live publication and measured device targets remain owner gates.


## Notes

**2026-10-28T15:10:03Z**

Outgoing response evidence: contracta5e30000 four expected RED0.22s; behavior72feaea8 native/controller/seed/transport36PASS38.02s; one CODE review active. Exact measured archive_publish.py wc -l397 before403 after; behavior commit body406/412 is a transcription error, corrected here without rewriting history. Final seed spec, local operator checks and full-source gate remain open.
