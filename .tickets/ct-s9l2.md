---
id: ct-s9l2
status: closed
deps: []
links: []
created: 2026-11-18T09:08:29Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-ihe7
---
# DocMeta eval sets no MLX memory or cache cap

congress_docmeta.eval_blind (and fast-gemma4 main's scripts/eval_docmeta_blind.py, which it came from) never calls mx.set_memory_limit or mx.set_cache_limit. On 2026-11-18 04:05 an eval of gemma4_e2b_v64_c2c4_w8 on the merged engine showed a 30 GB footprint in top beside another 10 GB model job on the 48 GB Mac (247 MB unused, 15 GB in the compressor); stopping it freed about 21 GB. Earlier evals of the same model were reported near 10 GB peak MLX memory, so most of the footprint is probably MLX's buffer cache, not measured. The trainer caps both (--memory-limit-gb 38, cache 512 MB). Until fixed, run evals through .cache/archive-release/docmeta-move-20261117/capped_run.py (limit 24 GB, cache 2 GB).

## Acceptance Criteria

eval_blind and the sweep command take a memory limit with a safe default; a run beside a second 10 GB job leaves the machine with free memory; predictions are unchanged by the cap.


## Notes

**2026-11-20T17:29:15Z**

2026-11-20: Added mx.set_memory_limit and mx.set_cache_limit controls with safe defaults to congress_docmeta.silicon_runtime_v6, eval_blind, and cli (commit 0e554d3f). Verified in test_docmeta_audit_remediation.py and live Apple Silicon MLX hardware eval (.cache/archive-release/docmeta-move-20261117/eval_after_ct2cig_cts9l2_20261120.json).
