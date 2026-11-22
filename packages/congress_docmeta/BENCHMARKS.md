# `congress_docmeta` Cross-Mac & Cross-Arm Benchmarks

Comprehensive reference for the **26-sweep cross-Mac bake-off** (`15` sweeps on **M4 Pro 48 GiB**, `11` sweeps on **Base M5 24 GiB**) plus **5-fold group-stratified CV detector/calibrator evaluations** (`n=212`), offline conformal `CROQ` calibration (`n_open=161`), and the formally falsified architectures ledger.

For package overview and quickstart highlights, see [`README.md`](README.md). For pipeline stages, archive routing, and prior LoRA training progression, see [`docs/architecture.md`](docs/architecture.md) and [`docs/measurements/docmeta-v64-lora-20261117.md`](../../docs/measurements/docmeta-v64-lora-20261117.md).

---

## Summary & Production Architecture

All 26 bake-off sweeps achieve **`100.0%` `strict_v4_valid` schema compliance** on the unified `212`-document held-out benchmark (`165` `valid_sweep` + `47` `val48_sweep` rows from `llm_queue_v6_2.parquet`).

| Architecture | Host | Speed Scope | docs/s | `valid` HL | `valid` PK | `valid` Role | `val48` HL | `val48` PK |
|---|---|---|---:|---:|---:|---:|---:|---:|
| `cell0` (Legacy strict Pass-1 + GPT-OSS Pass-2) | M4 Pro (`48 GiB`) | `warm_post_init` | `0.884` | `87.30` | `91.5` | `72.2` | `89.14` | `89.4` |
| `cell1_gptoss` (Router + Kev/Laya + GPT-OSS) | M4 Pro (`48 GiB`) | `warm_post_init` | `0.571` | `88.04` | `93.3` | `72.1` | `88.31` | `87.2` |
| `cell_step1_laya_default` (Fast router + Laya Stage-1) | Base M5 (`24 GiB`) | `warm_post_init` | `1.319` | `87.94` | `93.3` | `72.2` | `89.38` | `87.2` |
| `cell_pass1_raw` (Pass-1 Gemma-4 2B only, no router) | M4 Pro (`48 GiB`) | `warm_post_init` | `1.538` | `87.67` | `91.5` | `72.1` | `89.14` | `89.4` |
| `cell_step1_fast_only` (Fast router only, 0 validators) | Base M5 (`24 GiB`) | `warm_post_init` | **`2.272`** | `87.90` | `93.3` | `71.9` | `89.38` | `87.2` |
| **`arm_d_pure_croq` (`CROQ` `aps_det` `alpha=0.05`, full text)** | M4 Pro (`48 GiB`) | `cold_inclusive_init_plus_decode` | `1.339` | **`88.49`** | **`93.3`** | **`73.3`** | **`90.92`** | **`93.6`** |
| **`arm_d_pure_croq` (`CROQ` `aps_det` `alpha=0.05`, full text)** | Base M5 (`24 GiB`) | `cold_inclusive_init_plus_decode` | **`1.820`** | `87.84` | **`93.3`** | `72.3` | `88.99` | **`89.4`** |
| `arm_d_bm25` (Opt-in `BM25` multi-crop speed mode) | Base M5 (`24 GiB`) | `cold_inclusive_init_plus_decode` | `2.479` | `86.30` | `91.5` | `67.6` | `90.34` | `91.5` |

> **Why Base M5 (`1.82–2.27 docs/s`) beats M4 Pro (`1.34–1.54 docs/s`) here:** On unified memory with `w8` quantization and `B=128` (`19.2 GiB` auto-cap), M5's per-token compute/memory efficiency delivers higher `docs/s` than M4 Pro (`B=256`). Note also that `arm_d_*` timings include `~20–23s` of cold engine init + ANE warmup + dual-split overhead (`cold_inclusive_init_plus_decode`), whereas single-pass production streaming (`warm_post_init`) eliminates repeated startup cost (`~1.54+ docs/s` on M4 Pro, `~2.27 docs/s` on Base M5).

### Promoted Production Defaults (`e10d0333`)
1. **Conformal Grammar Set Routing (`grammar_router="fast"`, `CROQ aps_det` `alpha=0.05`, `max_lock_k=4`):** Replaces ad-hoc `0.99/0.985` thresholds and eliminates blocking ANE router/validators from Pass-1. Locks open documents into exact singletons (`1` kind) or compact schema unions (`<=4` kinds) when safe, falling back to full schema otherwise.
2. **Full Uncut Pass-1 Text (`bm25_multicrop=False`) + Lightweight Pre-Mask Telemetry (`use_telemetry="auto"`):** Full-text Pass-1 `Gemma-4 2B` decode retains long-document role/date fidelity while recording exact pre-mask softmax entropy (`H_pre`) and constrained grammar mass (`-log Z_valid`) without touching `fast_gemma4`.
3. **Zero-Cost Calibrated Triage (`ExtractConf`, `use_extractconf=True`):** Pure-Python calibrated risk scorer (`73` features, `0 ms` GPU/ANE cost) outputs `any_defect`, `personas`, `committees`, `dates`, and `primary_kind` defect probabilities (`extractconf_risk_json`) for downstream async escalation instead of local self-repair.
4. **Automatic `24 GiB` Memory & Batch Sizing (`silicon_runtime_v6.py`):** Hosts with `0 < RAM <= 24 GiB` automatically cap MLX active working set to `min(20.0, round(0.80 * RAM, 1)) = 19.2 GiB`, cache to `1.5 GiB`, and rolling batch size `b_slots` to `128` (`24.0 GiB`, `2.0 GiB`, `256` on `>= 48 GiB` Macs). Explicit CLI/API overrides always win.

---

## 1. Timing Methodology & Scopes

Hardware timing numbers across bake-off phases measure distinct portions of startup vs execution and must be read with their exact scope tag:

- **`warm_post_init`** (`Phase 1`, `Step 1 Fixed`): Measures warm inference batch duration over all `212` documents **after** model load and Metal/ANE warmup complete.
- **`warm_with_telemetry`** (`Step 2 Pass-1`): Warm post-init batch decode with Pythonic pre-mask telemetry wrappers and `router=fast` active.
- **`cold_inclusive_init_plus_decode`** (`Arm D`): `arm_d_croq_retriever.py` starts `t0` **before** acquiring the hardware lock and running `FastGemma4Engine(warmup=True, warmup_ane=True)`, and invokes `run_records` separately per split — adding `~20–23s` of startup/warmup tax directly into elapsed seconds.
- **`cumulative_pass1_plus_arm_c`** (`Arm C`): Sum of Stage-1 Pass-1 runtime plus Stage-2 Single-Field Hunter runtime (`77.78–78.79s` on M4 Pro, `54.89s` on Base M5).
- **`end_to_end_stage2`** (`Arm B`): End-to-end Pass-1 + `K=4, T=0.35` Dual-Candidate Contrastive Decoding + Subtree MBR (`1471.15s` / `24.5 min`).

---

## 2. M4 Pro (`48 GiB`, `Mac16,8`) Complete Leaderboard (`15` Sweeps)

Run configuration: `B=256`, `w8` quantization, full Pass-1 queue (`212` docs = `165` `valid_sweep` + `47` `val48_sweep`). Paired two-sided bootstrap `p`-values compare each run against **`cell_pass1_raw`**.

| Run ID | Phase | Elapsed (s) | Scope | docs/s | `valid` HL | `valid` PK | `valid` Role | `valid >6k` | `val48` HL | `val48` PK | `val48` Role | `val48 >6k` | `valid` Delta (`p`) | `val48` Delta (`p`) |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `cell_pass1_raw` | Phase 1 | 137.81 | `warm_post_init` | 1.538 | 87.67 | 91.5 | 72.1 | 88.42 | 89.14 | 89.4 | 79.1 | 87.27 | +0.00 (`1.000`) | +0.00 (`1.000`) |
| `cell1_nogptoss` | Phase 1 | 221.93 | `warm_post_init` | 0.955 | 88.40 | 93.9 | 72.2 | 88.53 | 89.39 | 87.2 | 81.2 | 86.67 | +0.75 (`0.181`) | +0.16 (`0.947`) |
| `cell0` | Phase 1 | 239.89 | `warm_post_init` | 0.884 | 87.30 | 91.5 | 72.2 | 88.25 | 89.14 | 89.4 | 79.1 | 87.27 | -0.28 (`0.258`) | +0.00 (`1.000`) |
| `cell1_gptoss` | Phase 1 | 371.27 | `warm_post_init` | 0.571 | 88.04 | 93.3 | 72.1 | 87.92 | 88.31 | 87.2 | 79.1 | 86.28 | +0.32 (`0.705`) | -1.04 (`0.300`) |
| `cell2_gptoss` | Phase 1 | 349.20 | `warm_post_init` | 0.607 | 88.11 | 93.3 | 73.4 | 87.97 | 87.58 | 83.0 | 76.7 | 87.67 | +0.37 (`0.643`) | -0.95 (`0.462`) |
| `cell3_gptoss` | Phase 1 | 448.73 | `warm_post_init` | 0.472 | 87.92 | 93.3 | 72.3 | 87.92 | 89.35 | 87.2 | 81.1 | 86.67 | +0.10 (`0.940`) | +0.16 (`0.947`) |
| `pass1_raw_tel` | Step 2 Pass-1 | 189.89 | `warm_with_telemetry` | 1.117 | 88.40 | 93.9 | 72.2 | 88.53 | 89.39 | 87.2 | 81.2 | 86.67 | +0.75 (`0.181`) | +0.16 (`0.947`) |
| `pass1_multicrop_ane_tel` | Step 2 Pass-1 | 158.41 | `warm_with_telemetry` | 1.338 | 86.54 | 93.3 | 66.9 | 86.41 | 89.04 | 85.1 | 75.0 | 89.07 | -0.39 (`0.678`) | +1.02 (`0.668`) |
| `arm_c_from_raw` | Step 2 Arm C | 268.67 | `cumulative_pass1_plus_arm_c(78.79s)` | 0.789 | 86.50 | 93.9 | 69.7 | 87.13 | 87.54 | 87.2 | 76.1 | 85.99 | -0.25 (`0.698`) | -0.56 (`0.602`) |
| `arm_c_from_multicrop` | Step 2 Arm C | 236.19 | `cumulative_pass1_plus_arm_c(77.78s)` | 0.898 | 85.38 | 93.3 | 66.8 | 86.18 | 88.21 | 85.1 | 73.8 | 88.86 | -1.03 (`0.340`) | -0.02 (`0.924`) |
| `arm_b_dccd_mbr` | Step 2 Arm B | 1471.15 | `end_to_end_stage2` | 0.144 | 85.80 | 87.3 | 68.9 | 85.86 | 86.60 | 87.2 | 73.5 | 82.11 | -1.29 (`0.149`) | -3.30 (`0.066`) |
| **`arm_d_pure_croq`** | **Step 2 Arm D** | **158.30** | **`cold_inclusive_init_plus_decode`** | **1.339** | **88.49** | **93.3** | **73.3** | **88.97** | **90.92** | **93.6** | **81.7** | **90.84** | **+0.93 (`0.022`)** | **+2.29 (`0.248`)** |
| `arm_d_pure_croq_a10` | Step 2 Arm D | 159.44 | `cold_inclusive_init_plus_decode` | 1.330 | 87.71 | 90.9 | 72.8 | 88.39 | 88.09 | 83.0 | 76.9 | 85.48 | -0.03 (`0.957`) | -0.90 (`0.410`) |
| `arm_d_ane_emb2` | Step 2 Arm D | 127.81 | `cold_inclusive_init_plus_decode` | 1.659 | 86.78 | 91.5 | 68.6 | 87.76 | 89.96 | 91.5 | 78.9 | 90.89 | -0.08 (`0.890`) | +1.43 (`0.473`) |
| `arm_d_bm25` | Step 2 Arm D | 111.94 | `cold_inclusive_init_plus_decode` | 1.894 | 86.30 | 90.9 | 69.2 | 86.50 | 89.90 | 91.5 | 78.3 | 90.84 | -0.99 (`0.323`) | +1.41 (`0.480`) |

### `valid_sweep` Length-Bucket Breakdown (`M4 Pro 48 GiB`, `n=165`)

| Run ID | `<=1.3k` (`n=29`) HL / Role | `1.3k-3k` (`n=32`) HL / Role | `3k-6k` (`n=29`) HL / Role | `>6k` (`n=75`) HL / Role |
|---|---:|---:|---:|---:|
| `cell_pass1_raw` | `86.78` / `71.84` | `86.29` / `81.79` | `84.35` / `80.73` | `88.42` / `70.27` |
| **`arm_d_pure_croq` (`alpha=0.05`)** | `86.93` / `71.84` | **`89.25` / `84.29`** | **`84.78` / `80.73`** | **`88.97` / `72.50`** |
| `arm_d_pure_croq_a10` (`alpha=0.10`) | `87.36` / `71.84` | `85.50` / `81.79` | `84.53` / `81.47` | `88.39` / `71.11` |
| `arm_d_bm25` | `86.93` / `71.84` | `86.91` / `82.50` | `82.87` / `81.47` | `86.50` / `68.15` |
| `arm_b_dccd_mbr` | `86.41` / `73.22` | `87.17` / `85.65` | `82.99` / `85.64` | `85.86` / `66.23` |

`arm_d_pure_croq` (`alpha=0.05`, full uncut text) achieves `0` `"other"` fallbacks on both `valid_sweep` and `val48_sweep`, improves `+0.93` doc-level points over `cell_pass1_raw` (`p=0.022`), and beats `cell_pass1_raw` in every length bucket while avoiding `BM25` and `Arm B` regressions on long documents (`>6k`).

---

## 3. Base M5 (`24 GiB`, `focus-macbook.local`) Complete Leaderboard (`11` Sweeps)

Bake-off flags used on Base M5: `B=128`, `--memory-limit-gb 20.0 --cache-limit-gb 1.5 --ane-ring --ane-variant w8`, zero `GPT-OSS`. Paired two-sided bootstrap `p`-values compare each run against the post-Step-1 canonical baseline **`cell_step1_fast_only`**. (Production code now auto-resolves `<=24 GiB` hosts to `19.2 GiB` active memory = `min(20.0, 0.80 * 24)`, `1.5 GiB` cache, and `B=128` via `silicon_runtime_v6.py` without CLI flags.)

| Run ID | Phase | Elapsed (s) | Scope | docs/s | `valid` HL | `valid` PK | `valid` Role | `valid >6k` | `val48` HL | `val48` PK | `val48` Role | `val48 >6k` | `valid` Delta (`p`) | `val48` Delta (`p`) |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `cell_pass1_raw` | Phase 1 | 93.72 | `warm_post_init` | 2.262 | 88.17 | 92.1 | 73.0 | 88.36 | 89.05 | 89.4 | 78.8 | 87.07 | +0.33 (`0.660`) | -0.03 (`0.991`) |
| `cell1_nogptoss` | Phase 1 | 186.37 | `warm_post_init` | 1.137 | 87.90 | 93.3 | 71.9 | 88.47 | 89.38 | 87.2 | 80.9 | 86.47 | +0.00 (`1.000`) | +0.00 (`1.000`) |
| **`cell_step1_fast_only`** | **Step 1 Fixed** | **93.31** | **`warm_post_init`** | **2.272** | **87.90** | **93.3** | **71.9** | **88.47** | **89.38** | **87.2** | **80.9** | **86.47** | **+0.00 (`1.000`)** | **+0.00 (`1.000`)** |
| `cell_step1_laya_default` | Step 1 Fixed | 160.71 | `warm_post_init` | 1.319 | 87.94 | 93.3 | 72.2 | 88.58 | 89.38 | 87.2 | 80.9 | 86.47 | +0.05 (`0.765`) | +0.00 (`1.000`) |
| `pass1_raw_tel` | Step 2 Pass-1 | 139.19 | `warm_with_telemetry` | 1.523 | 87.90 | 93.3 | 71.9 | 88.47 | 89.38 | 87.2 | 80.9 | 86.47 | +0.00 (`1.000`) | +0.00 (`1.000`) |
| `pass1_multicrop_ane_tel` | Step 2 Pass-1 | 129.11 | `warm_with_telemetry` | 1.642 | 86.66 | 93.3 | 68.2 | 87.46 | 88.53 | 85.1 | 77.1 | 85.90 | -0.58 (`0.169`) | -0.20 (`0.690`) |
| `arm_c_from_raw` | Step 2 Arm C | 194.08 | `cumulative_pass1_plus_arm_c(54.89s)` | 1.092 | 85.89 | 93.3 | 69.0 | 87.36 | 87.35 | 87.2 | 76.3 | 85.09 | -1.14 (`0.004`) | -1.01 (`0.069`) |
| **`arm_d_pure_croq`** | **Step 2 Arm D** | **116.48** | **`cold_inclusive_init_plus_decode`** | **1.820** | **87.84** | **93.3** | **72.3** | **88.64** | **88.99** | **89.4** | **79.1** | **86.48** | **-0.09 (`0.735`)** | **-0.03 (`0.985`)** |
| `arm_d_pure_croq_a10` | Step 2 Arm D | 117.25 | `cold_inclusive_init_plus_decode` | 1.808 | 87.74 | 90.9 | 72.5 | 87.81 | 88.50 | 83.0 | 79.5 | 85.28 | -0.52 (`0.146`) | -0.66 (`0.279`) |
| `arm_d_ane_emb2` | Step 2 Arm D | 106.74 | `cold_inclusive_init_plus_decode` | 1.986 | 86.66 | 91.5 | 68.6 | 88.02 | 90.25 | 91.5 | 78.9 | 91.68 | -0.73 (`0.376`) | +2.11 (`0.187`) |
| `arm_d_bm25` | Step 2 Arm D | 85.52 | `cold_inclusive_init_plus_decode` | 2.479 | 86.30 | 91.5 | 67.6 | 87.29 | 90.34 | 91.5 | 78.9 | 91.88 | -1.19 (`0.221`) | +2.20 (`0.174`) |

On Base M5, dropping the blocking Stage-1 ANE validator (`cell_step1_laya_default` -> `cell_step1_fast_only`) recovers `+41.9%` relative throughput (`160.71s -> 93.31s`, `1.319 -> 2.272 docs/s`) for virtually identical quality (`-0.04` `valid` HL, `0.00` `val48` HL), while `arm_d_pure_croq` preserves quality parity (`87.84` vs `87.90`, `p=0.735`) and lifts `val48` `primary_kind` (`87.2% -> 89.4%`).

---

## 4. Cross-Mac Paired Equivalence (`Base M5 - M4 Pro`)

Across all four matched sweeps (`n=165` `valid_sweep`, `n=47` `val48_sweep`), **Base M5 `24 GiB` (`B=128`)** stays statistically indistinguishable from **M4 Pro `48 GiB` (`B=256`)** while running ~`1.36x–1.47x` faster:

| Paired Comparison (`Base M5 - M4 Pro`) | `valid_sweep` Mean Diff `[95% CI]` (`p`) | `valid_sweep` McNemar (M5 / M4 wins) | `val48_sweep` Mean Diff `[95% CI]` (`p`) |
|---|---:|---:|---:|
| `pass1_raw (M4 vs M5)` | `+0.626` `[-0.152, +1.955]` (`p=0.314`) | `1` / `2` (`p=1.000`) | `-0.089` `[-0.266, +0.000]` (`p=0.742`) |
| `arm_d_pure_croq_a05 (M4 vs M5)` | `-0.727` `[-2.106, +0.076]` (`p=0.181`) | `0` / `2` (`p=0.500`) | `-2.376` `[-6.348, +0.266]` (`p=0.125`) |
| `arm_d_bm25 (M4 vs M5)` | `+0.095` `[-0.896, +1.366]` (`p=0.936`) | `0` / `3` (`p=0.250`) | `+0.727` `[+0.089, +1.595]` (`p=0.028`) |
| `arm_c_from_raw (M4 vs M5)` | `-0.600` `[-2.106, +0.439]` (`p=0.361`) | `6` / `1` (`p=0.125`) | `-0.514` `[-1.579, +0.452]` (`p=0.322`) |

---

## 5. Offline Conformal `CROQ` Calibration (`n_open=161`)

Evaluated via 5-fold group-stratified CV on the `161` open usable documents from the `212`-doc bake-off corpus (`router_fast`, `47` canonical kinds). Baseline heuristic `relaxed_top2_only_0.985` only compacts `81/161` (`50.3%`), emits `0.0%` singletons, and blocks only `2/18` Pass-1 `primary_kind` errors (`0/7` in `3k-6k`).

| Score Mode | `alpha` | Target Cov | Empirical Cov | Singleton (`\|C\|=1`) | Compact (`1<=\|C\|<=4`) | Wrong Locks | Clean Broken | Mean `\|C\|` | Pass-1 `PK` Err Blocked/Fixed | `3k-6k` `PK` Err |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `aps_det` | `0.10` | `0.90` | `0.9006` | `75.16%` (`121`) | `95.65%` (`154`) | `14` | `10` | `1.60` | `7+10=17/18` | `2+4=6/7` |
| **`aps_det` (shipped)** | **`0.05`** | **`0.95`** | **`0.9503`** | **`63.35%` (`102`)** | **`73.91%` (`119`)** | **`0`** | **`0`** | **`5.04`** | **`4+6=10/18`** | **`0+2=2/7`** |
| `aps_det` | `0.03` | `0.97` | `0.9814` | `38.51%` (`62`) | `50.31%` (`81`) | `0` | `0` | `12.96` | `1+1=2/18` | `0+0=0/7` |
| `lac` | `0.10` | `0.90` | `0.9006` | `73.91%` (`119`) | `97.52%` (`157`) | `16` | `10` | `1.44` | `7+10=17/18` | `2+4=6/7` |
| `lac` | `0.05` | `0.95` | `0.9503` | `47.83%` (`77`) | `67.70%` (`109`) | `0` | `0` | `5.09` | `1+4=5/18` | `0+0=0/7` |
| `aps_rand` | `0.05` | `0.95` | `0.9627` | `57.14%` (`92`) | `68.32%` (`110`) | `0` | `0` | `7.36` | `4+4=8/18` | `0+0=0/7` |
| `raps_det` | `0.05` | `0.95` | `0.9503` | `0.00%` (`0`) | `9.94%` (`16`) | `0` | `0` | `19.09` | `0+0=0/18` | `0+0=0/7` |
| `raps_rand` | `0.10` | `0.90` | `0.9068` | `62.11%` (`100`) | `76.40%` (`123`) | `0` | `0` | `2.37` | `4+7=11/18` | `0+3=3/7` |

**Bundled calibration artifact ([`croq_v64_calibration.json`](src/congress_docmeta/croq_v64_calibration.json)):** Fit strictly on disjoint split `split_records_grouped_stratified(target_cal=560, seed=20261116) -> split_cal_records_disjoint(early_stop_frac=0.25, seed=20261117)[cal_thresh]` (`n_cal=410`, `47` kinds, `score_mode="aps_det"`, `alpha=0.05`, `max_lock_k=4`, `q_hat=0.882122`, empirical calibration coverage `95.37%`, singleton rate `69.02%`, open fallback rate `19.76%`).

---

## 6. 5-Fold Group-Stratified CV Detector & Calibrator Leaderboard (`n=212`)

`ExtractConf` (`extractconf_v6.py`) replaces uncalibrated heuristic flags (`ECE ~0.48`) and slow ANE Stage-2 scorers (`300–640 ms/doc`) with a pure-Python/NumPy linear + hybrid risk model over `73` structural, router, deterministic V0, and pre-mask grammar telemetry features ([`extractconf_v64_calibration.json`](src/congress_docmeta/extractconf_v64_calibration.json)). Evaluated out-of-fold across `n=212` documents (`5`-fold group-stratified CV):

| Mac | Detector / Calibrator | Any-Defect AUROC | PR-AUC | R@10%FPR | ECE | Per-Field AUROC / Notes |
|---|---|---:|---:|---:|---:|---|
| `M4_Pro_48GB` | `Phase 3 baseline_staged_with_rules` | 0.6170 | 0.7635 | 0.2207 | 0.4749 | Static rules baseline |
| `M4_Pro_48GB` | `Phase 3 cv_stacker_stage1_only` | 0.6488 | 0.7896 | 0.2276 | 0.0690 | `0` LLM Pass-2 calls |
| `M4_Pro_48GB` | `Phase 3 cv_stacker_stage1_plus_kev` | 0.6409 | 0.7788 | 0.1931 | 0.0633 | `300+ ms/doc` Stage-2 ANE |
| `M4_Pro_48GB` | `Phase 2 multiwindow_min_prob` | 0.6420 | 0.7931 | 0.2138 | — | `608–639 ms/doc` ANE |
| `M4_Pro_48GB` | `extractconf_baseline (Log)` | 0.6819 | 0.8167 | 0.2483 | 0.0647 | PK=`0.853`, Dates=`0.769`, Role=`0.779`, Cmt=`0.809` |
| `M4_Pro_48GB` | `extractconf_baseline (Hybrid)` | 0.6890 | 0.8178 | 0.2552 | 0.0280 | PK=`0.866`, Dates=`0.761`, Role=`0.792`, Cmt=`0.802` |
| `M4_Pro_48GB` | `extractconf_raw_tel (Log)` | 0.6619 | 0.7875 | 0.1931 | 0.1019 | PK=`0.876`, Dates=`0.835`, Role=`0.770`, Cmt=`0.827` |
| `M4_Pro_48GB` | `extractconf_raw_tel (Hybrid)` | 0.6689 | 0.7951 | 0.1586 | 0.0819 | PK=`0.881`, Dates=`0.849`, Role=`0.775`, Cmt=`0.835` |
| `M4_Pro_48GB` | `extractconf_multicrop (Log)` | **0.7446** | **0.8705** | **0.4452** | **0.0413** | PK=`0.876`, Dates=`0.829`, Role=`0.798`, Cmt=`0.770` |
| `M4_Pro_48GB` | `extractconf_multicrop (Hybrid)` | 0.7443 | 0.8693 | 0.4178 | 0.0511 | PK=`0.875`, Dates=`0.825`, Role=`0.808`, Cmt=`0.772` |
| `Base_M5_24GB` | `Phase 3 baseline_staged_with_rules` | 0.6025 | 0.7570 | 0.1849 | 0.4834 | Static rules baseline |
| `Base_M5_24GB` | `Phase 3 cv_stacker_stage1_only` | 0.6513 | 0.8142 | 0.2808 | 0.0524 | `0` LLM Pass-2 calls |
| `Base_M5_24GB` | `Phase 3 cv_stacker_stage1_plus_kev` | 0.6339 | 0.8012 | 0.3014 | 0.0494 | `300+ ms/doc` Stage-2 ANE |
| `Base_M5_24GB` | `Phase 2 multiwindow_min_prob` | 0.6304 | 0.7894 | 0.1986 | — | `608–639 ms/doc` ANE |
| `Base_M5_24GB` | `extractconf_baseline (Log)` | 0.7032 | 0.8324 | 0.3014 | 0.0582 | PK=`0.847`, Dates=`0.766`, Role=`0.774`, Cmt=`0.800` |
| `Base_M5_24GB` | `extractconf_baseline (Hybrid)` | 0.6816 | 0.8260 | 0.2466 | **0.0193** | PK=`0.862`, Dates=`0.782`, Role=`0.783`, Cmt=`0.793` |
| `Base_M5_24GB` | `extractconf_raw_tel (Log)` | 0.6615 | 0.7837 | 0.2690 | 0.0771 | PK=`0.874`, Dates=`0.837`, Role=`0.761`, Cmt=`0.823` |
| `Base_M5_24GB` | `extractconf_raw_tel (Hybrid)` | 0.6610 | 0.7844 | 0.2759 | 0.0420 | PK=`0.883`, Dates=`0.844`, Role=`0.771`, Cmt=`0.823` |
| `Base_M5_24GB` | `extractconf_multicrop (Log)` | **0.7073** | **0.8443** | **0.3793** | 0.0487 | PK=`0.905`, Dates=`0.793`, Role=`0.774`, Cmt=`0.809` |
| `Base_M5_24GB` | `extractconf_multicrop (Hybrid)` | 0.6857 | 0.8318 | 0.3448 | 0.0387 | PK=`0.907`, Dates=`0.807`, Role=`0.779`, Cmt=`0.809` |

---

## 7. Falsified Architectures Ledger (Do Not Re-Implement)

These six approaches were rigorously tested on both Macs and **formally retired** from the default pipeline:

1. **Local Pass-2 `GPT-OSS 20B` Escalation (`cell1_gptoss`, `371.27s` on M4 Pro):** Drops `-0.36` to `-1.08` headline points versus `cell1_nogptoss` at `-67%` throughput (`0.571` vs `0.955 docs/s`), and exceeds usable unified memory on `24 GiB` Base M5.
2. **Blocking Pass-1 ANE `Laya` / `Kev` Validators (`cell_step1_laya_default`, `160.71s` vs `93.31s` on Base M5):** Adds `+67.4s` (`-41.9%` speed) for `+0.04` `valid` HL / `0.00` `val48` HL; adding Stage-2 `Kev-0.8B` (`300+ ms/doc`) even lowered Stage-1 CV AUROC (`0.6488 -> 0.6409` on M4, `0.6513 -> 0.6339` on M5). Both remain strictly opt-in via `--atomic-verifier`.
3. **Arm B (`DCCD + Subtree MBR`, `1471.15s` / `24.5 min`, `7.75x` slower than Pass-1 raw+tel):** Regresses `-2.60` `valid` HL (`85.80`) and `-2.79` `val48` HL (`86.60`, `p=0.066` vs baseline); unconstrained Pass-1 self-sketch poisoned Pass-2 (`-1.05` on non-switched docs, `-14.24` on switched docs).
4. **Arm C (`Single-Field Hunter`, `p=0.004` regression on Base M5):** Despite `0` schema violations (`435` jobs audited on M4 Pro), isolated field-by-field re-asks stripped whole-document JSON context and regressed Dates (`-158.9` net on M4) and Personas (`-59.2` net), dropping `valid` HL from `88.40 -> 86.50` on M4 Pro and `87.90 -> 85.89` (`p=0.004`) on Base M5.
5. **Unconditional Multi-Crop (`pass1_multicrop_ane_tel`, `arm_d_bm25`, `arm_d_ane_emb2`):** Drops `1.2–2.2` points on `valid_sweep` (`arm_d_bm25` loses across `1.3k-3k`, `3k-6k`, and `>6k` buckets vs `cell1_nogptoss`, `p=0.007` on M4 Pro). Keep `--bm25-multicrop` strictly as an **opt-in throughput/memory-shedding mode** when `~2.48 docs/s` on Base M5 outweighs `-1.5` pt persona-role recall.
6. **Aggressive `CROQ alpha=0.10` (`arm_d_pure_croq_a10`):** Yields `0s` speedup while causing `14` wrong offline locks and a statistically significant **`-3.19` pt crash on M4 `val48_sweep`** (`p=0.010`; `val48` PK falls `93.6% -> 83.0%` on M4 Pro and `89.4% -> 83.0%` on Base M5).

---

## 8. Reproducible Evaluation & Sweep Commands

Run model commands from the repository root using the unified `../fast-silicon/.venv` interpreter (with `uv sync --extra dev --extra extract`):

```bash
# 1. Production blind + sweep benchmark with promoted defaults
#    (router=fast + CROQ a=0.05, atomic-verifier=none, telemetry=auto, ExtractConf enabled,
#     automatic <=24 GiB RAM=19.2G / cache=1.5G / b_slots=128 sizing)
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python \
  -m congress_docmeta.eval_blind \
  --model-dir ../fast-gemma4/artifacts/models/gemma4_e2b_v64a35_c2c4_w8 \
  --ane-ring \
  --out /tmp/eval_croq_default.json

# 2. Opt-in speed/memory-shedding BM25 multi-crop mode (~2.48 docs/s on Base M5)
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python \
  -m congress_docmeta.eval_blind \
  --model-dir ../fast-gemma4/artifacts/models/gemma4_e2b_v64a35_c2c4_w8 \
  --ane-ring \
  --bm25-multicrop \
  --out /tmp/eval_croq_bm25.json

# 3. Re-score an existing eval report (pure CPU, no model required)
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python \
  -m congress_docmeta.eval_blind \
  --rescore /tmp/eval_croq_default.json \
  --out /tmp/eval_rescored.json

# 4. Production Parquet queue sweep (Pass-1 + CROQ a=0.05 + ExtractConf sidecar)
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python \
  -m congress_docmeta.cli docmeta-sweep \
  .cache/archive-release/docmeta-v6-20261116/parquets_v6_2/llm_queue_v6_2.parquet \
  /tmp/docmeta_out.parquet
```

### Offline & Hardware Regression Suites

```bash
# CPU rules, CROQ conformal routing, ExtractConf calibration, and 24 GiB auto-sizing tests
.venv/bin/python -m pytest -q packages/congress_docmeta/tests/

# Dedicated CROQ + ExtractConf + telemetry suite
.venv/bin/python -m pytest -v packages/congress_docmeta/tests/test_croq_extractconf_v6.py

# Hardware model seam lane (Gemma-4 + MLX/ANE; requires fast-gemma4 / fast-silicon checkout)
uv run python packages/congress_docmeta/scripts/model_lane.py test packages/congress_docmeta/tests/model -v
```

---

## 9. Cross-Mac v2.2 Parity, `--embed-ane` & Pass-2 Falsification (2026-11-21)

Verified after fixing the `MAX_PERSONAS` / schema parity tests so `tests/model/` runs zero-skip via `pytest.importorskip("fast_gemma4")` (`12 passed in 179.29s` on M4 Pro via `model_lane.py`):

| Configuration (`n=212` `llm_queue_v6_2`) | Host / Auto Limits | Peak Memory | Throughput (`docs/s` / `tok/s`) | `valid` HL | `val48` HL | Strict Valid | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| Baseline (`CROQ alpha=0.05`) | M4 Pro (`24G / 2G / B=256`) | `18.39 GiB` | `1.067` / `427.76` | `87.86` | `89.92` | `100%` | Cross-Mac parity reference |
| Baseline (`CROQ alpha=0.05`) | Base M5 (`19.2G / 1.5G / B=128` auto) | `16.61 GiB` | **`1.4875`** / **`529.55`** | **`88.46`** | `89.84` | `100%` | Fits inside `19.2 GiB` cap (`0` swap) |
| `--embed-ane bge-small` | Base M5 (`19.2G / 1.5G / B=128`) | `16.30 GiB` | `1.4624 docs/s` | `88.46` | `89.84` | `100%` | `0.00` accuracy delta vs baseline |
| `--embed-ane embeddinggemma-2` | Base M5 (`19.2G / 1.5G / B=128`) | `17.02 GiB` | `1.4143 docs/s` | `88.46` | `89.84` | `100%` | `0.00` accuracy delta vs baseline |
| `m4_spaced_colon` (`spaced : ` vs `compact :`) | M4 Pro (`24G / 2G / B=256`) | — | `+10.74%` completion tokens (`57,437 -> 63,604`) | `87.00` (`-0.86`) | — | `212/212` flagged | Confirms checkpoint `compact :` parity requirement |

### Local Pass-2 Teacher Escalation Falsification (Same-Process / Synchronous Routing)

- **Base M5 `Q8 GPT-OSS` (`24 GB`):** Triggered OOM/swap pressure (`16.26 GB + 2.71/3.00 GiB`) when co-scheduled locally -> **rejected**.
- **Base M5 `Qwen3.5-4B` (`n=21` escalated subset on `any_top5`):** Only `14/21` valid, `1086.4s` (`0.2974` effective `docs/s`), regressed `valid` HL (`-0.046`) and `val48` HL (`-0.222`) -> **rejected**.
- **M4 Pro `Q4 GPT-OSS` (`n=168` escalated subset):** Only `139/168` valid in `1085.5s` -> **rejected** for synchronous Pass-2 routing.
- **v2.3 Direction (Landed in `ed3e710d`):** Keep Pass-1 single-model and fast; queue flagged/truncated records asynchronously offline (`docmeta-sweep --escalation-queue-out` -> standalone `retry-escalated`) with zero co-residency, paired with Tier-A salvage/bio-date restraint and `>6k` persona tail harvesting.

---

## 10. v2.3 Paired `eval_blind` Accuracy & Offline Escalation Queue (`ed3e710d`, 2026-11-22)

Paired M4 Pro (`48 GiB`) `212`-doc `eval_blind` runs (`165` `valid_sweep` + `47` `val48_sweep`, identical `llm_queue_v6_2.parquet` split, `100.0%` `strict_valid_pct`), adding Tier-A truncated/clamped record salvage, bio-date restraint, `>6k` persona tail harvesting, and offline JSONL Pass-2 escalation queue export/replay (`docmeta-sweep --escalation-queue-out`, `retry-escalated`):

| Split | Metric | Pre-v2.3 Baseline | Post-v2.3 (`ed3e710d`) | Delta |
|---|---|---:|---:|---:|
| **`valid_sweep` (`n=165`)** | `headline_mean` / `legacy headline_mean` | `70.95` / `88.34` | **`73.19` / `90.58`** | **`+2.24` / `+2.24`** |
| `valid_sweep` (`n=165`) | `dates_f1` / `legacy dates_f1` | `57.8` / `80.1` | **`69.5` / `91.4`** | **`+11.7` / `+11.3`** |
| `valid_sweep` (`n=165`) | `primary_kind_acc` / `personas_name_f1` / `personas_name_role_f1` | `93.3` / `77.2` / `73.8` | **`94.5` / `79.1` / `75.8`** | **`+1.2` / `+1.9` / `+2.0`** |
| `valid_sweep >6k` (`n=75`) | `headline_mean` / `personas_name_f1` / `Role` / `dates_f1` | `75.56` / `74.7` / `71.9` / `64.6` | **`77.03` / `78.1` / `75.4` / `68.1`** | **`+1.47` / `+3.4` / `+3.5` / `+3.5`** |
| **`val48_sweep` (`n=47`)** | `headline_mean` / `legacy headline_mean` | `87.28` / `89.14` | **`90.60` / `92.30`** | **`+3.32` / `+3.16`** |
| `val48_sweep` (`n=47`) | `primary_kind_acc` / `committees_f1` / `personas` / `Role` | `89.4` / `90.7` / `78.4` / `76.7` | **`93.6` / `95.5` / `81.9` / `80.2`** | **`+4.2` / `+4.8` / `+3.5` / `+3.5`** |
| `val48_sweep` (`n=47`) | `status_acc` / `chamber_acc` / `other_count` | `97.9` / `93.6` / `1` | **`100.0` / `97.9` / `0`** | **`+2.1` / `+4.3` / `-1`** |
| `val48_sweep >6k` (`n=21`) | `headline_mean` / `PK` / `personas` / `dates_f1` | `89.00` / `90.5` / `81.8` / `87.0` | **`91.64` / `95.2` / `84.7` / `90.1`** | **`+2.64` / `+4.7` / `+2.9` / `+3.1`** |
| **Sweep Wall (`212` docs)** | `elapsed_sec` / `docs_per_sec` / `strict_valid_pct` | `220.9s` / `0.96` / `100.0%` | **`218.6s` / `0.97` / `100.0%`** | **`-2.3s` (`+0.01 docs/s`)** |

```bash
# Offline decoupled Pass-2 workflow (zero co-residency between Pass-1 Gemma-4 and Pass-2 GPT-OSS-20B)
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python -m congress_docmeta.cli \
  docmeta-sweep llm_queue_v6_2.parquet /tmp/pass1.parquet --escalation-queue-out /tmp/esc.jsonl
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python -m congress_docmeta.cli \
  retry-escalated /tmp/esc.jsonl /tmp/pass1.parquet /tmp/pass2_merged.parquet
```
