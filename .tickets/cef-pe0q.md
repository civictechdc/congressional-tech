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

