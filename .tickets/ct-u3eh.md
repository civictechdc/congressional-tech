---
id: ct-u3eh
status: open
deps: [ct-flq8, ct-2uc9]
links: [ct-2cig, ct-jmwq, ct-2uc9, ct-flq8]
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

