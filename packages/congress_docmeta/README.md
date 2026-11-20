# congress-docmeta

DocMeta reads a congressional document's first pages and writes one `DocMetaV4Causal` record: kind, chamber,
congress, committees, dates, people and their roles, citations, a title and a gist. Most of the work is
deterministic (rules, parsers, lookups); a small language model fills in what the rules cannot.

This package owns all of it except the base Gemma-4 generation engine and generic ANE/MLX decision-model runners:
rules R1 to R8, parsers, the schema, prompts, conformal `CROQ` grammar routing, pre-mask telemetry + `ExtractConf`
risk scoring, the sweep driver, Congressional validator/router wrappers (`atomic_validator_v6.py`,
`grammar_router_ane_v6.py`, `scripts/train_v63_validators.py`), the gold eval, and training-label building.
The generative model runs via [fast-gemma4](../../../fast-gemma4), and typed-question decision-model runners
(`LayaAneBackend`, `Kev08bMlxBackend`) live in [fast-decision-models](../../../fast-decision-models); neither
engine imports this package.

Moved here from fast-gemma4 `src/fast_gemma4/docmeta/` at commit 11dcf14 on 2026-11-17 (ct-ihe7), with generic
Laya/Kev decision-model runners (`fast_decision_models`) later extracted to `../fast-decision-models`. The module
files keep their names so each can be compared with its original.

## Headline Benchmarks & Production Defaults

Across our **`26`-sweep cross-Mac bake-off** (`15` sweeps on **M4 Pro `48 GiB`** + `11` sweeps on **Base M5 `24 GiB`**,
`212` held-out documents from `llm_queue_v6_2.parquet`), replacing multi-pass validators and local `GPT-OSS` retries
with **single-pass Gemma-4 2B (`router=fast` + Conformal `CROQ alpha=0.05`) + pure-Python `ExtractConf`** yields
higher quality at much higher throughput, with **`100.0%` `strict_v4_valid`** across all runs:

| Pipeline Configuration | Host | Throughput (`docs/s`) | `valid` HL | `val48` HL | `val48` PK | Notes |
|---|---|---:|---:|---:|---:|---|
| Legacy strict Pass-1 + `GPT-OSS` (`cell0`) | M4 Pro (`48 GiB`, `B=256`) | `0.88` | `87.30` | `89.14` | `89.4%` | Warm post-init |
| `cell1_gptoss` (`Router + Kev/Laya + GPT-OSS`) | M4 Pro (`48 GiB`, `B=256`) | `0.57` | `88.04` | `88.31` | `87.2%` | Warm post-init |
| `cell_step1_laya_default` (`Fast router + Laya`) | Base M5 (`24 GiB`, `B=128`) | `1.32` | `87.94` | `89.38` | `87.2%` | Warm post-init |
| Pass-1 `router=fast`, 0 blocking validators | M4 Pro / Base M5 | `1.54` / **`2.27`** | `87.67` / `87.90` | `89.14` / `89.38` | `89.4%` / `87.2%` | Warm post-init (`cell_pass1_raw` / `cell_step1_fast_only`) |
| **Promoted `CROQ alpha=0.05` + full text (`arm_d_pure_croq`)** | **M4 Pro (`48 GiB`) / Base M5 (`24 GiB`)** | `1.34` / **`1.82`**\* | **`88.49`** / `87.84` | **`90.92`** / `88.99` | **`93.6%` / `89.4%`** | **0 `"other"` fallbacks on M4; +`0.93` `valid` (`p=0.022`)** |

\*`arm_d_pure_croq` benchmark timing uses `cold_inclusive_init_plus_decode` (includes `~20–23s` engine load + ANE warmup + split overhead; warm streaming reaches `~1.54+ docs/s` on M4 Pro and `~2.27 docs/s` on Base M5).

**Key lessons learned & shipped defaults:**
- **Conformal `CROQ` (`alpha=0.05`, `aps_det`, `max_lock_k=4`) beats hard thresholds & `alpha=0.10`:** Safely locks `63.4%` of open docs to a singleton and `73.9%` to `<=4` kinds with `0` wrong offline locks (`95.03%` empirical coverage), whereas `alpha=0.10` causes `14` wrong locks and a `-3.19` pt M4 `val48` crash (`p=0.010`).
- **Keep full uncut Pass-1 text by default:** Unconditional `BM25` / ANE multi-crop drops `1.2–2.2` `valid_sweep` points (`p=0.007` on M4 Pro); `--bm25-multicrop` stays opt-in only for throughput-bound `~2.48 docs/s` M5 runs.
- **Zero-cost `ExtractConf` replaces blocking ANE/20B local repair:** Lightweight pre-mask telemetry + calibrated logistic/hybrid scoring delivers `0.707–0.745` any-defect AUROC (`0.876–0.907` PK, `0.807–0.844` Dates, `0.779–0.808` Role, `ECE ~0.04`) at `0 ms` model overhead for async downstream routing, while Pass-2 `GPT-OSS`, blocking Pass-1 `Laya/Kev`, Arm B `DCCD+MBR` (`1471s`), and Arm C `Single-Field Hunter` (`p=0.004` M5 regression) are retired from defaults.
- **`24 GiB` Base M5 auto-sizing out of the box:** `silicon_runtime_v6.py` auto-caps `<= 24 GiB` Macs to `19.2 GiB` (`0.80 * RAM`) MLX active memory, `1.5 GiB` cache, and `b_slots=128` (`24.0 GiB` / `2.0 GiB` / `256` on `>= 48 GiB` Macs) without manual flags.

See **[`BENCHMARKS.md`](BENCHMARKS.md)** for the full `26`-sweep leaderboards, paired cross-Mac equivalence CIs, 5-fold CV detector tables, falsified architectures ledger, and reproducible CLI commands, and [`docs/architecture.md`](docs/architecture.md) for pipeline stage internals.

## What is where

| Module | What it does |
|---|---|
| `docmeta_v4_causal.schema.json`, `prompt_v4.py`, `compact_wire_v6.py` | Output schema, the V4 prompt, and the compact wire format the current model is trained on |
| `pythonic_v6.py` | `pre_pass_v6`, `post_pass_v6`, `PythonicEngineV6.run_records` (records in, DocMeta out), and shared-prefix clamp guards |
| `pythonic_v5.py`, `expanded_rules_v5.py`, `provenance_rules_v5.py`, `multipage_rules_v5.py` | Validation, canonical key order, triage, Tier-1 signatures, URL and multi-page rules that V6 builds on |
| `hygiene_and_line_parsers_v6.py`, `cover_locks_v6.py`, `zero_llm_bypass_v6.py` | Text clean-up, line parsers, cover locks, and documents answered with no model call |
| `relational_rules_v6.py` | Rules R1 to R8: rosters, roles, addressed chairs, sponsors, addressees, subcommittees, work addresses |
| `citations_and_signals_v6.py`, `anomaly_router_v6.py` | Citations and short titles; rule-based anomaly signals |
| `grammar_router_ane_v6.py`, `croq_v64_calibration.json` | Pre-decode calibrated `router="fast"` + conformal `CROQ` (`alpha=0.05`, `aps_det`, `max_lock_k=4`) union grammar routing (plus optional ANE router) |
| `telemetry_v6.py`, `extractconf_v6.py`, `extractconf_v64_calibration.json` | Lightweight pre-mask grammar uncertainty telemetry (`H_pre`, `-log Z_valid`) and calibrated `ExtractConf` per-field risk scorer (`0 ms` model cost) |
| `lexical_multicrop_v6.py` | Opt-in CPU `BM25` / `TF-IDF` multi-crop evidence selector (`--bm25-multicrop`) |
| `silicon_runtime_v6.py` | OS/MLX/TF32/R8 preflight, MLX wired/memory scope lifecycle, and `24 GiB` vs `48 GiB` auto-sizing |
| `atomic_validator_v6.py` | Optional `Laya` ANE / `Kev-0.8B` atomic validators (`--atomic-verifier`, off by default) |
| `address_reader/` | Postal-address reader (a copy of Keeplist's, see its `__init__.py`) plus congressional additions |
| `parquet_runner_v6.py`, `cli.py`, `sidecar_builder.py` | Resumable queue sweep (`queue` Parquet in, sidecar Parquet out) and release sidecar builder |
| `gold.py`, `eval_blind.py`, `compare_evals.py` | Gold sets, the held-out split, training pairs, and blind end-to-end evals |

Staged optional Congressional ANE/MLX validator artifacts (`laya_typed/`, `kev_08b/`, `router_v63_*`,
`validator_v63_calibration.json`, and checksum manifest `atomic_validators_manifest.json`) live under
`<main checkout>/.cache/archive-release/docmeta-v6-20261116/atomic_validators` (`DOCMETA_VALIDATORS_DIR` or
`DOCMETA_V6_DATA_DIR` overrides it). Run `scripts/train_v63_validators.py --write-manifest-only` to pin/refresh
`atomic_validators_manifest.json`; `AtomicOutputValidatorV6` and `PreDecodeGrammarRouterV6` verify checksums on load.
Generic ANE CoreML / MLX runners and builders live in `../fast-silicon/packages/fast-decision-models` (synced from `../fast-decision-models`).

## Output contract

The sweep writes the columns `viewer_publication/docmeta_v6_1.py` requires (`link_key`, `doc_key`,
`saved_body`, `package_id`, `disposition`, `v6_route`, `filename`, `effective_format`, `primary_kind`, `status`,
`congress`, `chamber`, `committees`, `docmeta_json`, `strict_v4_valid`, `docmeta_source`), plus routing/triage metadata
(`croq_lock_type`, `croq_lock_spec`, `extractconf_risk_json`, `anomaly_score`, `anomaly_flags`, `needs_teacher_escalation`),
which `model/sql/document-docmeta-v6-1.sql` passes through to the release.

## Running with the model

Apple Silicon inference engines (`fast-gemma4`, `fast-gpt-oss`, `fast-decision-models`, `fast-bge-small`,
`fast-embeddinggemma-2`) are deliberately omitted from `congressional-tech/uv.lock`. Standardize on the single
unified `../fast-silicon/.venv` interpreter synced with its `extract` extra (which installs `pyarrow`,
`jsonschema`, and the pinned R8 postal-address dependencies `usaddress==0.5.14`, `pycountry==26.2.16`,
`msgspec-schemaorg==0.2.1`, `msgspec==0.21.1` alongside `mlx>=0.32.4` and all 7 `fast-*` packages):

```bash
cd ../fast-silicon && uv sync --extra dev --extra extract
```

Then run evals and sweeps with `congress_docmeta` on `PYTHONPATH` (`FAST_SILICON_PYTHON` overrides the default
`../fast-silicon/.venv/bin/python` in `scripts/model_lane.py`; `FAST_GEMMA4_PYTHON` remains a fallback). Both
the sweep runner and `model_lane.py` fail loudly at startup if any R8 or schema dependency is missing, run
Apple Silicon OS (`>=26.2`) / `mlx>=0.32.4` / `MLX_ENABLE_TF32` / RAM preflight checks, manage
`mx.set_wired_limit` cleanly, default to `router="fast"` + `CROQ alpha=0.05`, pre-mask telemetry + `ExtractConf`,
zero blocking ANE/GPT-OSS validators, and auto-size `<= 24 GiB` hosts (`19.2 GiB` active cap, `1.5 GiB` cache,
`b_slots=128`) vs `48+ GiB` hosts (`24.0 GiB`, `2.0 GiB`, `b_slots=256`):

```bash
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python -m congress_docmeta.eval_blind --model-dir ../fast-gemma4/artifacts/models/gemma4_e2b_v64a35_c2c4_w8 --ane-ring --out /tmp/eval.json
```

```bash
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python -m congress_docmeta.cli docmeta-sweep llm_queue_v6_2.parquet out.parquet
```

## Tests

- `tests/` (including [`test_croq_extractconf_v6.py`](tests/test_croq_extractconf_v6.py)): rules, parsers, schema, `CROQ` calibration, `ExtractConf`, `24 GiB` auto-sizing, address reader (`production-offline`).
- `tests/model/`: the engine seam (tokenizer, `llguidance`, ANE, MLX). Run with
  `.venv/bin/python scripts/dev.py test docmeta-model`; under `production-offline` they are collected and skip.

Local data (rosters lookup, gold sets, the queue) is read from
`<main checkout>/.cache/archive-release/docmeta-v6-20261116`; `DOCMETA_V6_DATA_DIR` overrides it. Tests that need
it skip when it is absent.
