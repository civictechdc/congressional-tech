# congress-docmeta

DocMeta reads a congressional document's first pages and writes one `DocMetaV4Causal` record: kind, chamber,
congress, committees, dates, people and their roles, citations, a title and a gist. Most of the work is
deterministic (rules, parsers, lookups); a small language model fills in what the rules cannot.

This package owns all of it except the model: rules R1 to R8, parsers, the schema, prompts, the sweep driver,
the output validators' questions, the gold eval and training-label building. The model is the
[fast-gemma4](../../../fast-gemma4) engine, which this package calls and which never imports this package.

Moved here from fast-gemma4 `src/fast_gemma4/docmeta/` at commit 11dcf14 on 2026-11-17 (ct-ihe7). The module
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
| `atomic_validator_v6.py`, `grammar_router_ane_v6.py` | Output validator and pre-decode kind router (ANE and MLX backends) |
| `gold.py`, `eval_blind.py`, `compare_evals.py` | Gold sets, the held-out split, training pairs, and the blind eval |

## Output contract

The sweep writes the columns `viewer_publication/docmeta_v6_1.py` requires (`link_key`, `doc_key`,
`saved_body`, `package_id`, `disposition`, `v6_route`, `filename`, `effective_format`, `primary_kind`, `status`,
`congress`, `chamber`, `committees`, `docmeta_json`, `strict_v4_valid`, `docmeta_source`), which
`model/sql/document-docmeta-v6-1.sql` passes through to the release.

## Running with the model

fast-gemma4 is an Apple Silicon checkout with no remote, so it is not in `uv.lock`. Anything that generates runs
under fast-gemma4's interpreter with this package on the path:

```bash
PYTHONPATH=packages/congress_docmeta/src ../fast-gemma4/.venv/bin/python -m congress_docmeta.eval_blind --model-dir ../fast-gemma4/artifacts/models/gemma4_e2b_v64_c2c4_w8 --out /tmp/eval.json
```

```bash
PYTHONPATH=packages/congress_docmeta/src ../fast-gemma4/.venv/bin/python -m congress_docmeta.cli docmeta-sweep llm_queue_v6_2.parquet out.parquet
```

## Tests

- `tests/`: rules, parsers, schema, validators' questions, address reader. Part of `production-offline`.
- `tests/model/`: the engine seam (tokenizer, llguidance, ANE, MLX). Run with
  `.venv/bin/python scripts/dev.py test docmeta-model`; under `production-offline` they are collected and skip.

Local data (rosters lookup, gold sets, the queue) is read from
`<main checkout>/.cache/archive-release/docmeta-v6-20261116`; `DOCMETA_V6_DATA_DIR` overrides it. Tests that need
it skip when it is absent.
