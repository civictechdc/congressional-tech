---
id: cef-xyfc
status: closed
deps: []
links: []
created: 2026-10-28T11:55:43Z
type: task
priority: 1
assignee: mikewolfd
---
# Keep nullable model join keys in native hash joins

Apply the lead’s DataFusion join finding: all keys use IS NOT DISTINCT FROM when any needs null-safety, with explicit non-null filters preserving prior equals semantics. Bind null/empty distinctions, all physical hash keys and row equality before full model scale.


## Notes

**2026-10-28T12:14:38Z**

Local repair2944a10b after6032c684/b1ee6b33 contracts:35 actual native endpoint, link, queue, model and controller checksPASS43.55s on885; physicalplans require all composite keys/NullsEqual and no residual, NULL/blank cases preserve old meaning. Independent CODE review APPROVE cx_daily_target_review/nullable-join-review.md. Full-corpus fit remains in D1/model release gates.
