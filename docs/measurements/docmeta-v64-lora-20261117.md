# DocMeta V6.4 LoRA (C2 + C4): results, 2026-11-17

> Moved from fast-gemma4 on 2026-11-17 (ct-ihe7). Paths written as `fast_gemma4/docmeta/...` or `scripts/eval_docmeta_blind.py` now mean `packages/congress_docmeta/src/congress_docmeta/...` and `python -m congress_docmeta.eval_blind`; model artifacts stay in fast-gemma4.

**Production model since 2026-11-18: `artifacts/models/gemma4_e2b_v64a35_c2c4_w8`** (LoRA on all 35 layers,
adapter in `artifacts/models/adapters_v64a35`; see "Follow-up training experiments"). The sections from "Sets" to
"Hybrid ANE prefill" describe its predecessor, `artifacts/models/gemma4_e2b_v64_c2c4_w8` (epoch one, last 23
layers, adapter in `artifacts/models/adapters_v64_c2c4`), compared against the model before it,
`fused_gemma4_e2b_qat_v4`, and the untuned BF16 base.
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
`--ane-variant fp16` now runs the ring on the FP16 bundle (it used to resolve W8 regardless), and the eval
report's `ane_ring_bundle` names the bundle the ring used, or is null when it fell back to GPU only. An FP16
ring run has not been made since; `v64_ep1_ring_fp16.json` predates this and is a W8 run.

### Two follow-ups, measured in one session (19:22 to 19:39)

- **Pad fix.** Inside a 48-token group pads were still written. `_scatter_ring_chunk` now writes real tokens
  only, on the GPU admit path and the ring tail alike.
- **Seven chunks.** The ring ran three 256-token chunks per doc (768 suffix tokens); it now runs every chunk
  the bundle's 1,920-token past can hold: seven after the 278-token prefix, 1,792 suffix tokens. The 96-slot
  ring then carries 13 docs per cohort instead of 16.

| V6.4 LoRA | GPU only | GPU only, pad fix | Ring | Ring, pad fix | Ring, pad fix, 7 chunks |
|---|---|---|---|---|---|
| `valid_sweep` headline / document kind | 89.3 / 89.6 | 89.8 / 89.6 | 89.7 / 89.6 | 89.6 / 89.0 | 89.9 / 89.6 |
| `val48_sweep` headline / document kind | 90.6 / 89.4 | 90.4 / 89.4 | 90.7 / 89.4 | 90.6 / 89.4 | 90.4 / 89.4 |
| Docs per second | 1.53 | 1.68 | 1.78, 1.76 | 1.92 | 2.00, 2.03 |

- **Accuracy does not separate the five configurations.** Headline spans 0.6 points on `valid_sweep` and 0.2 on
  `val48_sweep` with no consistent sign, and 80 to 140 of the 212 docs change some free-text field between any
  two. Neither change can be called an accuracy gain or loss on these sets.
- **The pad fix is a correctness fix.** Eight docs within 31 tokens of each other had 0 to 31 wrong
  sliding-window positions each in the first decode step's window (the predicted counts); with the fix 0 to 1,
  as few as prefilling one doc at a time.
- **Seven chunks are a speed gain:** 1.77 to 2.02 docs/s (+14%), about 36 h for the 258,440-row queue instead
  of 41 h. The pad fix adds nothing to that (next point).
- **Seven chained chunks hold KV fidelity.** Cosine against GPU per chunk: layers 0..11 0.9993 to 0.9995 in
  every chunk; layers 12..14 0.9979 to 0.9984 in chunks 0 to 4 and 0.9968 to 0.9972 in chunks 5 and 6. The
  GPU's own chunk-size noise floor is 0.9971 to 0.9995.
- **The pad fix does not change speed.** Its 11-17 runs read 8 to 10% faster, one run each (1.68 and 1.92 in
  the table). Six interleaved reruns on 11-18 did not repeat it: back-to-back pairs under like load agree
  within 2% in both directions (ring 140.9 s against 141.6 s, GPU only 166.5 s against 163.9 s; fast-gemma4
  `artifacts/eval/ring_speed_repeat_20261118/`). Other jobs loaded the machine during that rerun and the same
  code differed by 17% between its two runs, so sweep timings count only from an idle machine.
- The two seven-chunk runs differ on 6 docs, in `topics` and `gist` only; the two three-chunk runs are
  identical. Not investigated.
- Peak MLX memory was 9.6 GB. Reports and logs: `artifacts/eval/ring_followups_20261117/`.

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

## Follow-up training experiments, 2026-11-17 to 11-18

Epoch one (`gemma4_e2b_v64_c2c4_w8`) was the production model through these; the owner adopted the full-size
all-35-layer run on 2026-11-18.

- **All 35 layers at full size: adopted.** `train_lora_v64.py --num-layers 35 --ckpt-tokens 1500`, same 3,489
  items, 357 min. Held-out loss 0.2777 against 0.3114. Same code, ring on, against epoch one
  (`v64a35.json` vs `v64_ep1_main_ring7.json`):

| | Epoch one | All 35 layers | Smallest difference the set can detect |
|---|---|---|---|
| `valid_sweep` headline | 89.9 | **91.8** | 1.8 |
| `valid_sweep` document kind | 89.6 | 92.1 (7 fixed, 3 broken; paired interval -1.2 to +6.1) | 6.3 |
| `valid_sweep` people, name F1 | 80.3 | **84.4** | 5.6 |
| `valid_sweep` people, name + role F1 | 73.6 | **79.3** | about 5.6 |
| `val48_sweep` headline / kind | 90.4 / 89.4 | 91.0 / 89.4 | 2.9 / 10.4 |
| Output tokens over 212 docs | 53,283 | 57,287 | |

  The headline and role gains are just over what `valid_sweep` can detect; the kind gain is not established.
  Throughput read 2.01 docs/s against 2.42, but four CPU-heavy jobs shared the machine during this run, so it
  needs a quiet back-to-back timing. Like every checkpoint before commit 743f6c9, both models were trained with
  a `<|think|>` system turn that the sweep never sends, and on labels since found to carry values the text does
  not state (`artifacts/gap_swarm_20261118/SUMMARY.md`); no further training until that data is signed off.

- **Retrain on repaired labels: a tie.** `gemma4_e2b_v64r_c2c4_w8` adds the addressed chair / ranking member
  where the text names them. Held-out loss 0.3032 against 0.3114; headline 90.2 / 91.4 / 90.8 on `valid_sweep` /
  `val48_sweep` / `val48` against 89.7 / 90.7 / 91.0 on the same gold, and `docs8` 75.7 against 88.5 (one doc is
  12.5). Not adopted.
- **More data still helps.** The retrain's mid-run checkpoints, scored end to end:

| Batches (of 3,489) | 1,600 | 2,400 | 3,200 | 3,489 |
|---|---|---|---|---|
| Held-out loss | 0.343 | 0.318 | 0.304 | 0.303 |
| `valid_sweep` headline | 87.1 | 89.1 | 89.7 | 90.2 |
| `val48_sweep` headline | 87.6 | 89.3 | 91.4 | 91.4 |

- **Config sweep, 600 stratified docs, one epoch, 92-doc held-out loss.** Three baseline runs (two init seeds,
  one batch order) land within 0.002, so 0.004 is the bar.

| Run | Held-out loss | s/batch |
|---|---|---|
| Baseline: last 23 layers, lr 1.8e-4 | 0.3927, 0.3911, 0.3928 | 5.2 |
| lr 1e-4 | 0.3946 | 5.2 |
| lr 3e-4 | 0.4138 | 5.2 |
| All 35 layers (`--num-layers 35 --ckpt-tokens 1500`) | **0.3679** | 6.9 |
| E4B, all 42 layers (`--base-snap`, `--ckpt-tokens 0`) | **0.3398** | 11.5 |

- **E4B's lower loss did not become accuracy.** Free-running BF16 decode of both 600-doc adapters on 183
  held-out docs (`artifacts/logs/sweep/gen_compare.py`: no grammar, no rules, comparable only with itself): E4B
  headline 81.9 against E2B all-35 81.0, document kind 76.3 against 77.4 (13 against 15 docs right where the
  other is wrong), people name F1 67.0 against 70.6, at 16.9 s/doc against 11.4. A 0.028 loss gap bought
  nothing measurable, and E4B would need the packer, ANE bundle and native engine ported. Not pursued.
- **Loss is a weak proxy at this range.** It tied once (the retrain) and misled once (E4B), so the all-35 gain
  counts only when a full-size run is scored end to end.
- **Merged seven-chunk ring, re-scored on main** (`v64_ep1_main_ring7.json`): headline 89.9 / 90.4 on
  `valid_sweep` / `val48_sweep`, document kind unchanged, 2.42 docs/s in one run on an idle machine.

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
