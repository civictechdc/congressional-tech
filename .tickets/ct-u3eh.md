---
id: ct-u3eh
status: closed
deps: [ct-flq8, ct-2uc9]
links: [ct-2cig, ct-jmwq, ct-2uc9, ct-flq8, ct-o7j0]
created: 2026-11-18T22:04:50Z
type: task
priority: 2
assignee: mikewolfd
tags: [docmeta, gold]
---
# DocMeta: retrain on the signed-off V6.5 labels with the production prompt

Filed 2026-11-18 from /Users/mikewolfd/Work/congressional-tech/.cache/archive-release/docmeta-v65-raretypes-20261118/HANDOFF.md. BLOCKED by the owner hold of 2026-11-18: no training until he signs off the training and test data. The production model fast-gemma4/artifacts/models/gemma4_e2b_v64a35_c2c4_w8 was trained with a <|think|> turn that production never sends (fixed in fast-gemma4 743f6c9, carried into congress_docmeta.gold) and on the old labels. After sign-off: retrain with the fixed prompt, the sealed V6.5 labels, all 35 layers; cap biographies and transcripts, not witness statements. Commands after the DocMeta move (from /Users/mikewolfd/Work/fast-gemma4, python ~/.venv-vllm-metal/bin/python): PYTHONPATH=<CT checkout>/packages/congress_docmeta/src python -m congress_docmeta.training_pairs --base-snap <BF16 base snapshot> [--class-cap N] [--extra-train-jsonl PATH] --out X/pairs.json, then python scripts/train_lora.py --pairs X/pairs.json --checkpoint-config X/docmeta_wire_config.json --num-layers 35 --ckpt-tokens 1500 --skip-ane --adapter-dir A --out-model-dir Y. The class cap in training_pairs caps every class alike; capping only biographies and transcripts needs a small change there. Check prompts with .cache/archive-release/docmeta-move-20261117/prompt_parity_check.py before training.

## Acceptance Criteria

1. The owner sign-off is recorded on the review ticket. 2. Training pairs come from the sealed V6.5 file and pass prompt_parity_check.py (0 prompts with a thinking marker). 3. The new model is scored against v64a35 on the same sets with the fixed scorer (ct-2cig) and the result recorded; adoption is the owner call.


## Notes

**2026-11-22T18:41:11Z**

2026-11-22 V6.5 training & eval readiness: training_pairs.py now supports --strip-known and selective --cap-class KIND=N (resolving uniform --class-cap); pythonic_v5/v6, parquet_runner_v6, and eval_blind auto-detect strict_text_only / known_mode=none and support val48_v65/docs8_v65 (100.0 oracle on 165 heldout + blind sets); parse_gold_rows defaults augment_personas=False on split SSOT and R5 hyphen line-wrap bug is fixed. Retraining remains held pending ct-flq8 owner sign-off.

**2026-11-22T19:53:35Z**

2026-11-22 Horizon 0 audit & owner decision A2: Superseded by DocMeta V7 Core Reset (ct-o7j0) per docs/plans/docmeta-v7-consulting-plan-20261122.md. V6.5 SSOT (sha256 72f9d446..., 3,733 rows) stays preserved as raw/document seed input, but V6.5 training is halted because read-only audit found: 8.29% ungrounded personas (31.0% in hearing_transcript across 126 docs), 11.98% verbatim_title substring misses, 68.5% heldout_v6_4 / 50.0% blind_val48 House-event overlap with train, +36.3 to +68.9 pp v6_4_old-vs-v6_5_gapfill criteria drift, 8.52% (307/3603) Cleanlab label issues (22.9% in blind_val48), and structurally broken flat classes (multi_doc_packet F1=0.000, slides_or_visual F1=0.065, usable error_or_non_document).
