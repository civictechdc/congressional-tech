---
id: ct-jmwq
status: open
deps: []
links: [ct-u3eh, ct-2cig, ct-2uc9, ct-flq8]
created: 2026-11-18T22:04:50Z
type: task
priority: 2
assignee: mikewolfd
tags: [docmeta, gold]
---
# DocMeta: GPU checks of the 26-person format (branch docmeta-people-limit-26, ct-bult)

Filed 2026-11-18 from /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/docmeta-v65-raretypes-20261118/HANDOFF.md. Ticket ct-bult (raise the people limit from 10 to 26, output limit 768 to 1,536, role-based roster guard) exists only on the local branch docmeta-people-limit-26, worktree /Users/mikewolfd/Work/worktrees/ct-docmeta-people-limit, 5 commits ahead of origin/main and 5 behind when checked at 17:04 on 2026-11-18. It is not pushed; push and pull request are the owner call. The gold clean-up script and checker read DocMeta code from that worktree, so do not prune it. Not done there: (a) scripts/dev.py test docmeta-model on that branch (Apple Silicon, fast-gemma4 checked out); (b) a blind eval of the production model fast-gemma4/artifacts/models/gemma4_e2b_v64a35_c2c4_w8 on that branch: the prompt now says <=26 and the model was trained on <=10, so compare against artifacts/eval/v64a35.json with compare_modulo_work_addr.py in .cache/archive-release/docmeta-move-20261117/; use a GPU-only run when an exact match is expected, because ring runs change gist or topics wording in 3 to 7 of 212 documents between runs; (c) a quiet-machine timing of the production model (2.0 against 2.4 docs/s was measured under load). Eval command, from /Users/mikewolfd/Work/fast-gemma4: PYTHONPATH=<that worktree>/packages/congress_docmeta/src .venv/bin/python -m congress_docmeta.eval_blind --model-dir artifacts/models/production --label L --out artifacts/eval/L.json (add --ane-ring for the ring). Scoring existing models is allowed under the training hold.

## Acceptance Criteria

1. docmeta-model full lane exit 0 on the branch. 2. Blind eval of the production model on the branch recorded beside the 10-person baseline, with every metric that moved named. 3. Quiet-machine docs/s recorded. 4. ct-bult updated with the results and either pushed as a pull request on the owner word or closed.

