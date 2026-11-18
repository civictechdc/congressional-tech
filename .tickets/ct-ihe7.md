---
id: ct-ihe7
status: in_progress
deps: []
links: [ct-fk4w]
created: 2026-11-17T19:47:13Z
type: task
priority: 2
assignee: mikewolfd
tags: [docmeta, model, packages]
---
# Move the DocMeta pipeline from fast-gemma4 into CT as packages/congress_docmeta

Owner ruling 2026-11-17: fast-gemma4 holds only model-related code; congressional and parsing logic belongs in CT, which calls fast-gemma4 for generation. Today the whole DocMeta pipeline (rules R1 to R7, parsers, rosters lookups, schema, prompts, sweep driver, gold eval, label building) lives in fast-gemma4 at src/fast_gemma4/docmeta/ (32,373 lines). Rule R8 and the address reader wait on the unmerged fast-gemma4 branch feat/work-addr-address-reader (tip 11dcf14). The sidecar builder is unversioned in .cache/archive-release/docmeta-v6-20261116/scripts_v6_2/. Plan and owner answers: side-session note docmeta-move-plan-20261117.md.

## Acceptance Criteria

1. packages/congress_docmeta owns rules, parsers, schema, prompts, sweep driver, validators' DocMeta half, gold eval, label building, R8, the address reader and the sidecar builder. 2. fast-gemma4 holds no congressional rules, parsers, rosters or DocMeta schema; CT imports it, never the reverse. 3. The eval run from CT reproduces fast-gemma4 artifacts/eval/v64_ep1_r8_after.json exactly on val48, docs8, valid_sweep and val48_sweep with model gemma4_e2b_v64_c2c4_w8. 4. Sidecar columns still satisfy viewer_publication/docmeta_v6_1.py; model/ and publish-model.json unchanged. 5. Moved tests pass under each repo's own runner. 6. uv.lock changes only by added entries.


## Notes

**2026-11-17T20:08:53Z**

2026-11-17: 5778dd44 (verbatim move, no-model comparison identical on 34,916 items) and 451f7c4d (generic helper and scorers taken from fast-gemma4, training pairs as a file) on branch ct-docmeta-move, local only. Model proof waits on the fast-gemma4 retrain (PID 94092).

**2026-11-17T20:24:19Z**

2026-11-17 evening: branch ct-docmeta-move at f5e1276d (7 local commits). No-model checks done: old vs moved code identical on 34,916 items; training pairs hash the same; uv.lock +146/-0; package tests 32 pass through dev.py (partial run); docmeta-model lane 7 pass against fast-gemma4 branch refactor/docmeta-to-ct (ecbdd61). Waiting on the fast-gemma4 retrain for the eval reproduction: .cache/archive-release/docmeta-move-20261117/run_model_proof.sh. Not pushed; fast-gemma4 branch not merged.

**2026-11-18T09:08:37Z**

2026-11-18 04:01 model proof on the engine the reference was made on (fast-gemma4 refactor/docmeta-to-ct ecbdd61): eval from CT code as moved (93dd5141) and from 92221ef3 both reproduce artifacts/eval/v64_ep1_r8_after.json on val48, docs8, valid_sweep, val48_sweep: 0 predictions, 0 per-doc records, 0 metrics differ; the later commit adds only the sweep counters pass2_escalated/pass2_accepted. docmeta-model full lane: 9 passed, exit 0. fast-gemma4 tests on the branch: 40 passed, 1 failed (test_native_gemma4_ane_cli, MLComputePlan timeout, fails on main too). Output: .cache/archive-release/docmeta-move-20261117/run_model_proof.out. Then fast-gemma4 main moved to fdfe088; its DocMeta-side changes are in 0ddaa72a and main is merged into the branch (b4e956e). Still to run once the training session's queue writes QUEUE3_DONE: run_merged_checks.sh (CT eval against main's own eval on the new engine, compared with work_addr set aside; fast-gemma4 tests; model lane), then the merge into fast-gemma4 local main, which the owner approved on 2026-11-17 ('Yes, after retrain'). Follow-up filed: ct-s9l2.
