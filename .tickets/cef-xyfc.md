---
id: cef-xyfc
status: in_progress
deps: []
links: []
created: 2026-10-28T11:55:43Z
type: task
priority: 1
assignee: mikewolfd
---
# Keep nullable model join keys in native hash joins

Apply the lead’s DataFusion join finding: all keys use IS NOT DISTINCT FROM when any needs null-safety, with explicit non-null filters preserving prior equals semantics. Bind null/empty distinctions, all physical hash keys and row equality before full model scale.

