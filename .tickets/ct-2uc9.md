---
id: ct-2uc9
status: open
deps: []
links: [ct-u3eh, ct-2cig, ct-jmwq, ct-flq8]
created: 2026-11-18T22:04:50Z
type: task
priority: 2
assignee: mikewolfd
tags: [docmeta, gold]
---
# DocMeta gold: land the V6.5 dataset tooling in packages/congress_docmeta

Filed 2026-11-18 from the training session handoff: /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/docmeta-v65-raretypes-20261118/HANDOFF.md (read it first). None of the tooling built on 2026-11-18 for the DocMeta gold labels is in a repository; it lives only under /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/docmeta-v65-raretypes-20261118 on one Mac. What to land, through a fresh branch from origin/main and a pull request: the clean-up script scripts/normalize_gold_v6_5.py (rules X, K, F, G1, A1, C1, C2; 214 KB); the contract and checker contract/gold_contract.py with contract/CONTRACT.md, docmeta_gold_conventions.schema.json and adjudications.jsonl (28 waivers); the single source-of-truth layout ssot/ (docmeta_gold_v6_5.jsonl plus MANIFEST.json; the data file itself stays in the cache, only its sha256 and the builder belong in git); the review viewer viewer/ (build_bundle.py, serve.py, app.js); and the labeling conventions in ANNOTATION_RUBRIC.md, section V6.5 House Conventions. Verified 2026-11-18 17:04: ssot/docmeta_gold_v6_5.jsonl is 3,733 rows with sha256 33f978210cbeb8f25960fb66c96090b8139d2e4f2321e64dd7f8e53b56ce9b3f, and MANIFEST.json gives train 3,268, heldout_v6_4 180, test_gapfill 179, blind_val48 48, blind_docs8 8, excluded 50. The clean-up script and the checker currently read DocMeta code from the unpushed worktree /Users/mikewolfd/Work/worktrees/ct-docmeta-people-limit (branch docmeta-people-limit-26, ticket ct-bult, which exists only on that branch), so decide the order: land ct-bult first, or make the tooling run against main. congress_docmeta.gold still reads the V6.4 gold and heldout_v6_4_183_link_keys.json; switching training_pairs and eval_blind to the sealed V6.5 file is part of this ticket. The scorer defect in ct-2cig (a value the label lacks must count as an error) has to be fixed before any score on the text-only labels is quoted.

## Acceptance Criteria

1. The clean-up script, checker, contract, schema, adjudications, manifest builder, viewer and rubric conventions are in packages/congress_docmeta on main, with tests that run in production-offline. 2. Re-running clean-up then check from the repository reproduces the sealed file sha256, or the difference is explained. 3. training_pairs and eval_blind read the sealed V6.5 file and its splits; the held-out documents are unchanged. 4. No hard-coded path into another worktree remains.

