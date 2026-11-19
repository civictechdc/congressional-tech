# congress-docmeta

DocMeta reads a congressional document's first pages and writes one `DocMetaV4Causal` record: kind, chamber,
congress, committees, dates, people and their roles, citations, a title and a gist. Most of the work is
deterministic (rules, parsers, lookups); a small language model fills in what the rules cannot.

This package owns all of it except the base Gemma-4 generation engine and generic ANE/MLX decision-model runners:
rules R1 to R8, parsers, the schema, prompts, the sweep driver, the Congressional validator/router wrappers
(`atomic_validator_v6.py`, `grammar_router_ane_v6.py`, `scripts/train_v63_validators.py`), the gold eval and
training-label building. The generative model runs via [fast-gemma4](../../../fast-gemma4), and typed-question
decision-model runners (`LayaAneBackend`, `Kev08bMlxBackend`) live in
[fast-decision-models](../../../fast-decision-models); neither engine imports this package.

Moved here from fast-gemma4 `src/fast_gemma4/docmeta/` at commit 11dcf14 on 2026-11-17 (ct-ihe7), with generic
Laya/Kev decision-model runners (`fast_decision_models`) later extracted to `../fast-decision-models`. The module
files keep their names so each can be compared with its original.

## What is where

| Module | What it does |
|---|---|
| `docmeta_v4_causal.schema.json`, `prompt_v4.py`, `compact_wire_v6.py` | Output schema, the V4 prompt, and the compact wire format the current model is trained on |
| `pythonic_v6.py` | `pre_pass_v6`, `post_pass_v6`, and `PythonicEngineV6.run_records` (records in, DocMeta out) |
| `pythonic_v5.py`, `expanded_rules_v5.py`, `provenance_rules_v5.py`, `multipage_rules_v5.py` | Validation, canonical key order, triage, Tier-1 signatures, URL and multi-page rules that V6 builds on |
| `hygiene_and_line_parsers_v6.py`, `cover_locks_v6.py`, `zero_llm_bypass_v6.py` | Text clean-up, line parsers, cover locks, and documents answered with no model call |
| `relational_rules_v6.py` | Rules R1 to R8: rosters, roles, addressed chairs, sponsors, addressees, subcommittees, work addresses |
| `citations_and_signals_v6.py`, `anomaly_router_v6.py` | Citations and short titles; scoring of suspect outputs |
| `address_reader/` | Postal-address reader (a copy of Keeplist's, see its `__init__.py`) plus congressional additions |
| `parquet_runner_v6.py`, `cli.py` | The sweep: queue Parquet in, sidecar Parquet out, resumable |
| `atomic_validator_v6.py`, `grammar_router_ane_v6.py` | Congressional validator & pre-decode kind router (`fast-decision-models` backends) |
| `gold.py`, `eval_blind.py`, `compare_evals.py` | Gold sets, the held-out split, training pairs, and the blind eval |

Staged Congressional validator artifacts (`laya_typed/`, `kev_08b/`, `router_v63_*`, `validator_v63_calibration.json`,
and checksum manifest `atomic_validators_manifest.json`) live under
`<main checkout>/.cache/archive-release/docmeta-v6-20261116/atomic_validators` (`DOCMETA_VALIDATORS_DIR` or
`DOCMETA_V6_DATA_DIR` overrides it). Run `scripts/train_v63_validators.py --write-manifest-only` to pin/refresh
`atomic_validators_manifest.json`; `AtomicOutputValidatorV6` and `PreDecodeGrammarRouterV6` verify checksums on load.
Generic ANE CoreML / MLX runners and builders live in `../fast-silicon/packages/fast-decision-models` (synced from `../fast-decision-models`).

## Output contract

The sweep writes the columns `viewer_publication/docmeta_v6_1.py` requires (`link_key`, `doc_key`,
`saved_body`, `package_id`, `disposition`, `v6_route`, `filename`, `effective_format`, `primary_kind`, `status`,
`congress`, `chamber`, `committees`, `docmeta_json`, `strict_v4_valid`, `docmeta_source`), which
`model/sql/document-docmeta-v6-1.sql` passes through to the release.

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
`mx.set_wired_limit` cleanly, default Stage-2 `Kev-0.8B` batching to `--kev-batch-docs 8`, and engage
two-phase Pass-1 unload before loading `GPT-OSS-20B` on `<= 48 GiB` Macs (`--two-phase-pass2 auto`):

```bash
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python -m congress_docmeta.eval_blind --model-dir ../fast-gemma4/artifacts/models/gemma4_e2b_v64_c2c4_w8 --out /tmp/eval.json
```

```bash
PYTHONPATH=packages/congress_docmeta/src ../fast-silicon/.venv/bin/python -m congress_docmeta.cli docmeta-sweep llm_queue_v6_2.parquet out.parquet --kev-batch-docs 8 --two-phase-pass2 auto
```

## Tests

- `tests/`: rules, parsers, schema, validators' questions, address reader. Part of `production-offline`.
- `tests/model/`: the engine seam (tokenizer, llguidance, ANE, MLX). Run with
  `.venv/bin/python scripts/dev.py test docmeta-model`; under `production-offline` they are collected and skip.

Local data (rosters lookup, gold sets, the queue) is read from
`<main checkout>/.cache/archive-release/docmeta-v6-20261116`; `DOCMETA_V6_DATA_DIR` overrides it. Tests that need
it skip when it is absent.
