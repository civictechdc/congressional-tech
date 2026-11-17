# DocMeta V6.4 LoRA (C2 + C4): results, 2026-11-17

> Moved from fast-gemma4 on 2026-11-17 (ct-ihe7). Paths written as `fast_gemma4/docmeta/...` or `scripts/eval_docmeta_blind.py` now mean `packages/congress_docmeta/src/congress_docmeta/...` and `python -m congress_docmeta.eval_blind`; model artifacts stay in fast-gemma4.

Checkpoint: `artifacts/models/gemma4_e2b_v64_c2c4_w8` (adapter in `artifacts/models/adapters_v64_c2c4`).
Compared against the prior production model, `fused_gemma4_e2b_qat_v4`, and the untuned BF16 base.
Every number is the full pipeline (pre-pass, grammar-locked decode, post-pass with rules R4-R7) from
`scripts/eval_docmeta_blind.py`; raw reports are in `artifacts/eval/`.

## Sets

| Set | Docs | Path | Gold |
|---|---|---|---|
| `valid_sweep` | 165 | real `run_docmeta_parquet_sweep` on queue rows | held out of V6.4 gold, never trained on |
| `val48` | 48 | `PythonicEngineV6.run_records` | V4-era blind set |
| `val48_sweep` | 47 | real sweep on the val48 docs present in the queue | V4-era blind set |
| `docs8` | 8 | `run_records` | V4-era stress docs |

`valid_sweep` is weighted toward rare layouts (1,531 of the 2,000 cluster docs come from clusters of 2 to 14),
so it is harder than the corpus. One doc is 2 points on `val48` and 12.5 on `docs8`; repeat runs of the same
model moved `val48` document kind between 85.4 and 89.6.

## Result

| `valid_sweep` | Base BF16, zero-shot | Prior LoRA | V6.4 LoRA |
|---|---|---|---|
| Headline mean | 68.3 | 82.4 | **89.3** |
| Document kind | 59.1 | 78.7 | **89.6** |
| Committees F1 | 39.5 | 67.7 | **91.5** |
| Subcommittees F1 | 7.6 | 58.3 | **70.5** |
| Dates F1 | 57.6 | 84.9 | **89.9** |
| People, name F1 | 69.4 | 72.6 | **78.0** |
| People, name + role F1 | 50.5 | 64.0 | **71.2** |
| Refs F1 | 43.2 | 49.2 | **75.5** |
| Output tokens per doc | 423 | 308 | **249** |
| Flagged for escalation | 36 | 41 | **16** |

| Headline mean | Prior LoRA | V6.4 LoRA |
|---|---|---|
| `val48` | 88.1 | **91.0** |
| `val48_sweep` | 88.7 | **90.6** |
| `docs8` | 88.8 | 88.5 |

The base-model column predates rules R5-R7. Sweep throughput was between level and 17% faster across four
paired runs on a warm machine; it needs an interleaved ABBA run before a number is quoted. The token cut is
exact.

## What mattered

- **Train on what the sweep feeds.** The gold prompts serialized `known` with spaces and used a shorter text
  window than `llm_queue_v6_2.parquet` (the sweep's text is longer in 42% of docs, and its `known` is enriched
  in 15%). `train_lora_v64.py` rebuilds each prompt from the doc's queue row; `build_prompt_v6_compact`
  normalizes `known` so both production paths and training agree.
- **One epoch.** Held-out loss fell 2.47 -> 0.31 over 3,489 batches. A warm-restarted second epoch drove
  training loss to 0.23 while held-out loss rose to 0.37, and scored lower end to end (`valid_sweep` 87.5 vs
  89.3, `docs8` 76.1 vs 88.5).
- **One real label inconsistency, checked against the text.** In witness statements the addressed chair /
  ranking member is listed 92 to 100% of the time in the re-hydrated V4 and blind gold, 28% in the cluster and
  gap gold. Per-kind persona counts suggested the same for letters and bills; against the text they are fine
  (letters list 92% of addressees), and the count gap was document mix.
- **Deterministic rules beat more training for people.** Applied to the same model output, R4-R6 took
  `val48` name F1 77.2 -> 83.4 and `val48_sweep` 68.0 -> 78.0; R7 took subcommittees F1 78.4 -> 88.9 on
  `val48` and 62.9 -> 70.5 on `valid_sweep`.

| Rule | Fires on | Agreement with gold |
|---|---|---|
| R4 addressed chair / ranking member | `witness_statement` | 79 of 86 on consistent gold |
| R5 sponsor line | `bill_or_draft` | sponsor 58 of 60; cosponsors 72 of 94 |
| R6 addressees as `recipient` | five letter kinds | 174 of 182 named are gold personas |
| R7 subcommittee named or code-resolved | all | drops guesses from `cmt` codes; lookup alone agrees 71% |
| R8 `work_addr` of the person named above an address | statements, biographies, letters | 108 of 115 where gold gives that person an address |

## Hybrid ANE prefill: a tail-batching bug, fixed

With the compact prompt the Linear-W8 ring engages on DocMeta for the first time (the prior model never had a
valid W8 bundle on this machine). It first cost 3 to 6 points, all of it in documents longer than the 768
suffix tokens the ANE covers. Cause: `_admit_ane_cohort` finished every cohort's GPU tail as one padded batch,
so a shorter doc had pad KVs written past its end; in the sliding-window layers those wrap and overwrite its
last 512 real positions. The GPU admit path already groups docs within 48 tokens of each other; the tail path
now does the same. ANE compute itself was never the problem (per-layer KV cosine 0.998 to 1.000 against GPU).

| V6.4 LoRA | GPU only | Ring, before fix | Ring, fixed |
|---|---|---|---|
| `valid_sweep` headline / document kind | 89.3 / 89.6 | 86.0 / 84.1 | 89.7 / 89.6 |
| `val48_sweep` headline / document kind | 90.6 / 89.4 | 84.2 / 76.6 | 90.7 / 89.4 |
| Docs per second, same session | 1.51 | 1.86 | 1.86 |

The ring stays the default (`auto`): about 39 h for the 258,440-row queue against about 47 h GPU only.
`--ane-variant fp16` changes nothing because the ring always resolves the W8 runner.

## Work addresses (R8)

Keeplist's prose address reader is copied into `fast_gemma4.address_reader` (owner's decision: the projects stay
unrelated, so no shared package). The copy returns the same claims as the original on 7,258 documents.
`congressional.py` adds what this corpus writes differently: `N.W.` / `D.C.`, PO boxes, House and Senate office
rooms. Complete readings of gold street addresses: 231 -> 277 of 309. It needs the optional `address` extra;
without it R8 does nothing.

R8 gives an address to the person named in the block directly above it. It never replaces an address the model
wrote, and it skips committee letterheads, addresses inside a sentence and hearing rooms on testimony covers.

| Same model, same run settings | `work_addr` recall before | after | Other metrics |
|---|---|---|---|
| `val48` (11 gold addresses) | 54.5 (6) | 81.8 (9) | identical |
| `valid_sweep` (28) | 60.7 (17) | 64.3 (18) | identical |
| `val48_sweep` (11) | 72.7 (8) | 72.7 (8) | identical |

The before and after predictions differ in `work_addr` only, and the before run reproduces `v64_ep1_final.json`
exactly. R8 added 16 distinct addresses across the sets; all 16 are the office printed under that person's name.
Gold confirms 4 and is blank for the other 12, so precision against gold falls (`valid_sweep` 73.9 -> 60.0,
`val48` 66.7 -> 56.2) while agreement, over the people gold does give an address for, stays 100%. Gold
`work_addr` is too sparse to grade this field: on the training gold R8 also lands 63 addresses on people gold
leaves blank, and 11 of 12 read against the text were right (the wrong one, a hearing room, is now excluded).

Seen in passing, not fixed: the model sometimes gives a letter's recipients the sender's address
(`HHRG-116-IF17-20200128-SD031.pdf`), and R8 leaves a model-written address alone.

## Not done

- The Laya / Kev atomic validators were off for these numbers. With `laya-ane` on, scores did not move, flags
  rose from 16 to 23, and the small run slowed from 1.78 to 0.98 docs/s.
- The 258,440-row sweep and release cut.

## Reproduce

```bash
~/.venv-vllm-metal/bin/python scripts/train_lora_v64.py --ckpt-tokens 2400
.venv/bin/python scripts/eval_docmeta_blind.py --model-dir artifacts/models/gemma4_e2b_v64_c2c4_w8 --out artifacts/eval/v64.json
.venv/bin/python scripts/compare_docmeta_evals.py artifacts/eval/fused_v4_final.json artifacts/eval/v64.json
```
