---
id: ct-ihe7
status: in_progress
deps: []
links: []
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

