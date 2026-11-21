---
id: ct-jmwq
status: closed
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

## Notes

**2026-11-21**

Qualified on Apple M4 Pro (48 GiB) on rebased `docmeta-people-limit-26` using `/Users/mikewolfd/Work/fast-gemma4/artifacts/models/production` (`gemma4_e2b_v64a35_c2c4_w8`) and `DOCMETA_V6_DATA_DIR=/Users/mikewolfd/Work/congressional-tech/.cache/archive-release/docmeta-v6-20261116`:
1. `docmeta-model` full lane: `11 passed, 0 skipped in 668.58s (0:11:08)`, `docmeta-model (full lane): exit 0` (peak `2.52 GiB RSS, 5.38 GiB physical`).
2. Blind eval artifacts in `.cache/archive-release/docmeta-people-limit-26-20261121/`:
   - `eval_v64a35_p26_gpu.json` (GPU-only, peak `14.05 GiB RSS, 15.32 GiB physical`)
   - `eval_v64a35_p26_ring_quiet.json` (`--ane-ring`, quiet machine, peak `11.45 GiB RSS, 15.17 GiB physical`)
   - `gpu` and `ring_quiet` are 100% prediction-identical (`diff=0` across all 4 sets).
3. Metrics vs baselines (`eval_after_ct2cig_cts9l2_20261120.json` on `origin/main` and `fast-gemma4/artifacts/eval/v64a35.json`):
   - `val48` (`n=48`): `strict_valid_pct=100.0`, `primary_kind_acc=91.7` (unchanged), `headline_mean=89.47` (vs `90.2` `after_ct2cig`, `-0.73`), `personas_name_f1=79.6` (vs `82.6`, `-3.0`), `personas_name_role_f1=75.2` (vs `78.0`), `roster_spam_docs=1` (vs `0`), `docs_per_sec=0.596` (`80.5s` GPU) / `1.332` (`36.0s` `--ane-ring`, vs `1.429` `after_ct2cig`). Across all 48 docs, 46/48 kept identical persona counts (`TP=90, FN=29` unchanged; `FP` `9->17`): `doc#6` (`BILLS-115HR1719ih-JohnMuirNationalHistoricSiteExpansionAct.pdf`) extracted `10->17` real cosponsors (`+7 FP` only against V6.4's 10-capped gold), and `doc#36` (`Preliminary-Transcript-CMT-Vin-Database-Whistleblower-Bills-2015-9-25.pdf`, `run_records` path only) duplicated `Michael C. Burgess` as #11 on an already-leaking 10-member masthead (`10->11`, tripping `>10` `roster_shaped_members_v6`). In production sweep `val48_sweep[36]`, this doc emits 2 people and `roster_spam_docs=0`.
   - `docs8` (`n=8`): `strict_valid_pct=100.0`, `primary_kind_acc=87.5`, `personas_name_f1=84.2` (`0` persona diffs vs `v64a35`), `headline_mean=89.69` (vs `89.94` `v64a35`), `roster_spam_docs=0`, `docs_per_sec=0.502` (`15.9s` GPU) / `0.816` (`9.8s` `--ane-ring`).
   - `valid_sweep` (`n=165`, sweep of 212 docs with `val48_sweep`): `strict_valid_pct=100.0`, `primary_kind_acc=93.3` (vs `92.1` `after_ct2cig`, `+1.2`), `headline_mean=88.04` (vs `88.29`, `-0.25`), `personas_name_f1=75.6` (vs `77.5`, `-1.9`), `personas_name_role_f1=71.8` (vs `72.9`), `roster_spam_docs=0` (`0` in both `valid_sweep` and `val48_sweep`). `TP=239` and `FN=60` are unchanged; `FP` moved `79->94` (`+15`) from 3 docs: `doc#12` (`mansfield_letter_of_support_-_ave_maria_school_of_law_alumni.pdf`) extracted `10->24` real signatories/nominees (`+14 FP` against V6.4's 10-capped gold, `roster_shaped_members=0`), `doc#155` (`Treaty Doc. 116-1.pdf`, `0->3`), and `doc#84` (`HHRG-117-CN00-20210715-SD004.pdf`, `5->3`).
   - `val48_sweep` (`n=47`): `strict_valid_pct=100.0`, `primary_kind_acc=89.4`, `personas_name_f1=78.4` (vs `79.8` `v64a35`), `headline_mean=87.28` (vs `91.0` `v64a35`), `roster_spam_docs=0`.
   - Sweep throughput (`212 docs`): `0.833 docs/s` / `301.3 decode tok/s` GPU (`254.5s`); `0.995 docs/s` / `383.0 decode tok/s` `--ane-ring` (`213.0s`, vs `797.8 tok/s` / `2.008 docs/s` in `v64a35`). Speed/ANE note: `ane_ring_bundle` reported `None` (same as `eval_after_ct2cig` on Nov 20) because current `checkpoint_ane_key` returns `gemma4_e2b_v64a35_c2c4_w8-23022783aef2` while the on-disk bundle is keyed `...-51a0c36b2120`; `origin/main` also runs `ExtractConf` telemetry (`telemetry_wrapped_chunks=1`, `temperature=1e-4`).


