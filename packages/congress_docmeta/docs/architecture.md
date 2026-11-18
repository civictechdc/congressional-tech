# DocMeta V6 Deterministic Architecture, `323,564`-Row Routing & Blind Benchmarks

> Moved from fast-gemma4 on 2026-11-17 (ct-ihe7) to `packages/congress_docmeta/src/congress_docmeta/`, with generic decision-model runners/builders (`LayaAneBackend`, `Kev08bMlxBackend`, `native/laya_ane_runner.{h,mm}`) moved to `fast-decision-models` (and mirrored into the unified `fast-silicon` workspace). Congressional validator weights and `atomic_validators_manifest.json` live under `.cache/archive-release/docmeta-v6-20261116/atomic_validators` (`DOCMETA_VALIDATORS_DIR` overrides) while base Gemma-4 generation weights remain in `fast-gemma4`.

## 1. Overview

`congress_docmeta` packages the five-stage **DocMeta V6** deterministic extraction, text-hygiene, relational-graph, statutory-citation, per-slot grammar-locking, zero-LLM synthesis, and post-extraction anomaly-routing stack around the frozen `fused_gemma4_e2b_qat_v4` / `gemma4_e2b_v64a35_c2c4_w8` (`Gemma-4-E2B-it` QAT 4-bit + LoRA) model.

Key engineering properties:
- **100% Python Standard Library Isolation**: Importing and running `congress_docmeta` (`pre_pass_v6`, `post_pass_v6`, `triage_non_usable_v6`, `try_zero_llm_bypass_v6`, `extract_citations_and_signals_v6`, `score_docmeta_anomalies_v6`, `strict_validate_v4`, `silicon_runtime_v6`) requires zero external packages and passes `/usr/bin/python3 -B -I -S` isolation. `llguidance`, `mlx`, `pyarrow`, and `fast-*` engines are imported lazily only when instantiating constrained LLM/validator helpers.
- **Unified Apple Silicon Runtime & Two-Phase Memory Lifecycle**: Production sweeps run under `../fast-silicon/.venv/bin/python` (synced via `uv sync --extra dev --extra extract` so all `fast-*` engines and pinned R8 postal-address dependencies live in one venv). `parquet_runner_v6.py` enforces OS/MLX/TF32/RAM/R8 preflight checks, context-managed `mx.set_wired_limit`, inter-wave `mx.clear_cache()`, `kev_batch_docs=8` Stage-2 batching, serialized ANE ownership, explicit `enable_thinking=False` chat formatting (match `enable_thinking=False` on the next LoRA training cycle to eliminate historical `<|think|>` turn drift), and two-phase Pass-1 unload before loading `GPT-OSS-20B` Pass-2 on `<= 48 GiB` Macs.
- **Graceful Corpus Degradation**: Optional external lookup tables (`DOCMETA_V6_DATA_DIR`, defaulting to `<main checkout>/.cache/archive-release/docmeta-v6-20261116`, and `REFSPEC_ROOT`, defaulting to `../spicy-stack/RefSpec`) are loaded when present and degrade cleanly to pure-stdlib operation when absent.
- **Zero Prompt-Distribution Drift & Shared `1,368`-Token `prefix_kv`**: `pre_pass_v6` preserves the exact `<NONE>` advisory metadata format and raw text distribution expected by the Gemma-4 checkpoint while short-circuiting non-usable triage and high-confidence zero-LLM boilerplate documents prior to GPU execution, and keeping `SyncKindMatcher` fast-forward token alignment across per-slot `llguidance` grammars.

---

## 2. Five-Stage Pipeline (`packages/congress_docmeta/src/congress_docmeta/`)

1. **Stage 1 — Text Hygiene, CMS Stripping & Line Parsers (`hygiene_and_line_parsers_v6.py`, `expanded_rules_v5.py`, `multipage_rules_v5.py`)**:
   - Restores `\n`-preserved `p12_lines` and strips GPO `VerDate` headers/footers (`gpo_blank_after_strip` detection for blank un-OCR'd wrapper scans).
   - Repairs `BGsddV01` PDF symbol-font mojibake (`repair_bgsdd_mojibake_v6`) without corrupting legitimate currency (`¥`), Scandinavian characters (`Jørgensen`, `Bjørn`, `Sørensen`), or mathematical symbols (`≈`).
   - Strips `<script>`, `<style>`, and 11 recurring House/Senate Drupal/Evo CMS navigation wrapper families (`clean_html_and_cms_v6`, `strip_html_cms_nav_v5`) to prevent CMS time-travel Congress pollution, including bare-UUID Senate HTML files (`infer_is_html_v6`).
   - Enforces a strict PDF safety gate in `triage_non_usable_v6`: WAF/DataDome/CloudFront/soft-404 `error_pages` rules run **only** on HTML envelopes and **never** on PDFs (preventing false positives on hearings legitimately titled `"Access Denied: ..."`).
   - Runs line-anchored parsers for witness lists (`parse_witness_list_personas_v6`), `p3..p8` GPO `CONTENTS` / opening panels (`parse_gpo_p3_slice_personas_v6`), CBO `"At a Glance"` cost cards (`parse_cbo_cost_estimate_v6`), and GAO requester blocks (`parse_gao_requesters_v6`).

2. **Stage 2 — Provenance & Relational Graph Guards (`provenance_rules_v5.py`, `relational_rules_v6.py`)**:
   - Unwraps Wayback/WebHarvest/GovInfo URLs, repairs CreativeEngine `&download=1` suffixes missing `?`, maps 60+ House/Senate committee domains, all `29` House Select `hl..00` 2-letter Clerk codes, `7` statutory/chamber Commissions (`chamber="commission"`), and `84` human-adjudicated SHA overrides.
   - Enforces strict **Host-vs-Author** separation (`classify_hsru_host_status`, `can_fill_from_relational_v6`, `enrich_personas_from_relational_v6`):
     - Strips floor-repository host `hsru00` (`Committee on Rules`) misattribution on Rules Committee Prints, Comparative Prints, and referred bills.
     - Blocks relational host-committee/chamber overwrites on `external_report_or_whitepaper`, `agency_or_gao_crs_report`, cross-chamber `member_or_floor_statement`, and `-SD00x` supplemental exhibits (never stamping a meeting's `witness_key` as `author` of a `-SD00x` exhibit).
     - Uses `rosters_lookup_v6.json` (`12,770` Members, `284` committee codes) when available to enrich Bioguide `party_state`, subtract standing letterhead backbench rosters, and recover verified `Chair` / `Ranking Member` salutations.

3. **Stage 3 — Statutory, Regulatory & Congressional Citations (`citations_and_signals_v6.py`)**:
   - Combines linear-time `spicy-docs` / `RefSpec` statutory and regulatory scanners (`bill:`, `law:`, `usc:`, `cfr:`, `fr:`, `docket:`, `eo:`, `gao:`, `crs:`, `cbo:`) with Congressional procedural citations (`amdt:`, `rule:`, `rept:`, `hrg:`, `nom:`, `exhibit:`), proposed-bill `short_titles[]`, and `fiscal_years[]`.
   - Enforces all five `RefSpec` production safeguards:
     - `TRAP_1`: Preserves proposed new U.S.C. sections (e.g., `41 U.S.C. 8302A`) on legislative drafts (`bill_or_draft`, `committee_amendment`, `comparative_print`, `section_by_section`) while flagging/pruning `UscSectionOracle`-absent hallucinations (e.g., `49 U.S.C. 77`) on non-drafts.
     - `TRAP_2`: Bounds Executive Orders to `1 <= eo_num <= 14,420` and rejects XML/file-path homoglyphs (`\E043025.003.xml`).
     - `TRAP_3`: Maximal uninterrupted capitalized `... Act` noun-phrase matching (`Kelsey Smith Act` is never sub-sliced into `Smith Act`).
     - `TRAP_4`: Separates `ActRelative` statutory `refs[]` from standalone legislative `short_titles[]`.
     - `TRAP_5`: Strips left-margin bill line numbers (`1..26`) prior to longhand U.S.C./C.F.R. scans.

4. **Stage 4 — `100%`-Precision Cover Locks & Zero-LLM Synthesis (`cover_locks_v6.py`, `zero_llm_bypass_v6.py`)**:
   - Extends V5's 32 Tier-1 `doc_kind` signatures with cover locks for Senate `witness_statement`, Member-verified `member_opening_statement` (guarded by `detect_nominee_opening_override_v6` so SFRC executive/ambassador nominee `"Opening Statement of <Nominee>, Nominee to be ..."` is locked to `witness_statement`, never `member_opening_statement`), CBO cost estimates, and GAO reports (`114,624` total grammar-locked target rows).
   - Synthesizes complete, schema-valid `DocMetaV4Causal` JSON in pure Python (`0` GPU tokens) for unambiguous `truth_in_testimony_disclosure` (`15,988`), `witness_list` (`1,163`), `attendance_quorum_sheet` (`738`), and `legislative_schedule_or_calendar` (`199`) documents (`18,088` synthesized + `406` triaged = `18,494 / 18,494` `strict_validate_v4` pass).

5. **Stage 5 — Constrained Batch Decoding & Anomaly Router (`pythonic_v6.py`, `anomaly_router_v6.py`)**:
   - `PerDocGrammarHelperV6` + `SyncKindMatcher` compiles per-`doc_kind` `llguidance` JSON schemas lazily and synchronizes initial fast-forward tokens with `SCHEMA_V4_STR` so locked and unlocked documents share a single rolling GPU batch without token jitter.
   - `score_docmeta_anomalies_v6` / `route_batch_anomalies_v6` scores post-pass outputs for teacher escalation across empty actor-required personas, roster leaks (more than 10 Members of Congress outside a witness, cosponsor, signatory or recipient role), `primary_kind == "other"`, relational witness/committee/bioguide contradictions, invalid non-draft U.S.C. sections, and calendar/lock mismatches (`100.0%` specificity on `Gold360` gold; `100.0%` true-error precision on live V4/V5 outputs).

---

## 3. `323,564`-Row Archive Routing (`selected_release_id = 55c14dcd...f105`)

All `323,564` archive documents in `docmeta-v6-20261116` partition cleanly with zero unrouted rows (`68,098` `completed_no_llm` + `255,278` `llm_queue` + `188` `sha_dup_alias` = `323,564`):

| `v6_route` | Rows | Share | Execution Path |
|---|---:|---:|---|
| `upstream_spicydocs` | `49,604` | `15.33%` | `0` GPU tokens (`completed_no_llm_v6.parquet`) |
| `zero_llm_synthesized_docmeta` | `18,088` | `5.59%` | `0` GPU tokens (`completed_no_llm_v6.parquet`, `100%` `strict_validate_v4`) |
| `deterministic_triage_non_usable` | `406` | `0.13%` | `0` GPU tokens (`completed_no_llm_v6.parquet`, `100%` `strict_validate_v4`) |
| `sha_dup_alias` | `188` | `0.06%` | `0` GPU tokens (deduplicated via canonical `rn`) |
| `tier1_or_cover_or_anchor_grammar_locked` | `96,500` | `29.82%` | Per-slot `PerDocGrammarHelperV6` constrained LLM (`llm_queue_v6.parquet`) |
| `deterministic_enriched_open_kind` | `156,460` | `48.36%` | Deterministically enriched open-kind LLM (`llm_queue_v6.parquet`) |
| `cold_r2_metadata_only` | `2,284` | `0.71%` | Hydrate R2 body (`cold_r2_hydration_queue.parquet`) -> LLM |
| `llm_open_extraction` | `34` | `0.01%` | Standard constrained LLM (`llm_queue_v6.parquet`) |
| **Total** | **`323,564`** | **`100.00%`** | **`68,098` completed + `255,278` queue + `188` SHA aliases** |

---

## 4. Verification & Blind E2E Benchmark Summary

### 4.1 `Gold360` (`360` Docs)

| Configuration (`n = 360`) | `strict_v4` | `status` | `kind_exact` | `chamber` | `congress` | `cmt_f1` | `dates_f1` | `pers_name_f1` | `pers_role_f1` | `spam` | `avg_tok` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `Baseline Fused V4 LoRA` | `99.7%` | `99.2%` | `85.8%` | `98.3%` | `96.6%` | `86.1%` | `94.2%` | `72.2%` | `61.8%` | `13` | `306.1` |
| `Pythonic V5` | `100.0%` | `99.4%` | `88.9%` | `98.6%` | `99.6%` | `86.0%` | `94.3%` | `78.0%` | `66.7%` | `0` | `307.2` |
| **`Pythonic V6 (Rule-Isolated M=45)`** | **`100.0%`** | **`99.4%`** | **`89.2%`** | **`98.6%`** | **`99.6%`** | **`86.1%`** | **`94.5%`** | **`81.7%`** | **`71.1%`** | **`0`** | **`289.0`** |
| **`Pythonic V6 (Live 8x45 + 16 Bypass)`** | **`100.0%`** | `98.9%` | **`90.8%`** | **`98.6%`** | **`99.6%`** | `85.4%` | **`94.8%`** | **`80.6%`** | **`70.7%`** | **`0`** | **`289.0`** |

### 4.2 Blind Held-Out `val_48` (`48` Docs) & `docs_8` (`8` Hard Audit Docs) — `0 / 56` Regressions

| Split / Arm | `strict_v4` | `status` | `kind_exact` | `chamber` | `congress` | `cmt_f1` | `dates_f1` | `pers_name_f1` | `pers_role_f1` | `spam` | `avg_tok` | `time` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `val_48` — `Baseline Fused V4 LoRA` | `48/48` | `97.9%` | `87.5%` | `95.8%` | `77.5%` | `86.7%` | `88.3%` | `76.7%` | `62.0%` | `1` | `322.8` | `36.82s` |
| `val_48` — `Pythonic V5` | `48/48` | `97.9%` | `87.5%` | `95.8%` | `95.0%` | `86.7%` | `88.3%` | `79.3%` | `64.1%` | `0` | `322.8` | `37.50s` |
| **`val_48` — `Pythonic V6 (full+rel+bypass)`** | **`48/48`** | **`97.9%`** | **`87.5%`** | **`95.8%`** | **`95.0%`** | **`86.7%`** | **`88.3%`** | **`80.2%`** | **`65.0%`** | **`0`** | **`314.1`** | **`35.43s`** |
| `docs_8` — `Baseline Fused V4 LoRA` | `8/8` | `87.5%` | `87.5%` | `100.0%` | `87.5%` | `87.5%` | `100.0%` | `42.1%` | `36.8%` | `1` | `307.0` | `11.79s` |
| `docs_8` — `Pythonic V5` | `8/8` | `87.5%` | `100.0%` | `100.0%` | `100.0%` | `87.5%` | `100.0%` | `64.0%` | `56.0%` | `0` | `310.4` | `12.14s` |
| **`docs_8` — `Pythonic V6 (full+rel+bypass)`** | **`8/8`** | **`87.5%`** | **`100.0%`** | **`100.0%`** | **`100.0%`** | **`87.5%`** | **`100.0%`** | **`69.2%`** | **`61.5%`** | **`0`** | **`275.6`** | **`10.93s`** |

---

## 5. Quick Usage

```python
from congress_docmeta import (
    pre_pass_v6,
    post_pass_v6,
    score_docmeta_anomalies_v6,
    strict_validate_v4,
    try_zero_llm_bypass_v6,
)

enr_known, pre_meta = pre_pass_v6(
    known=None,
    filename="HHRG-118-JU00-TTF-SmithJ-20230510.pdf",
    text="Truth in Testimony Disclosure Form\nWitness Name: Jane Smith\nPosition: Director\nOrganization: Civic Lab\n...",
)
if pre_meta["zero_llm_docmeta"] is not None:
    clean_obj, sidecar = post_pass_v6(
        pre_meta["zero_llm_docmeta"],
        filename="HHRG-118-JU00-TTF-SmithJ-20230510.pdf",
        text="...",
    )
    ok, err = strict_validate_v4(clean_obj)
    assert ok, err
```

---

## 6. Release Sidecar Builder & Sweep Resume Ownership (`ct-0zry`)

### 6.1 Release-Parameterized Sidecar Builder (`sidecar_builder.py`)

`congress_docmeta.sidecar_builder.build_release_sidecar` (CLI: `python -m congress_docmeta.sidecar_builder` or `packages/congress_docmeta/scripts/build_docmeta_sidecar.py`) replaces the single-release `55c14dcda87a` migration script (`scripts/build_v6_2_ssot_sidecar.py`) as the maintained sidecar producer:
- Accepts any published release directory (`--release-dir`), optional `BodyTextSSOT` export directory (`--body-text-dir`), optional `body_text` selection JSON/gzip (`--selection`), and `--limit` for bounded verification.
- Applies current V6 rules (R4–R8, single-owner `HOUSE_CLERK_2LETTER_TO_CODE_V6`, and `ct-2cig` lock guards) and writes the three canonical sidecar parts (`completed_no_llm.parquet`, `llm_queue.parquet`, `sha_dup_alias.parquet`) plus `sidecar_manifest.json`.

### 6.2 Architectural Decision on Sweep Checkpointing vs `docspec-rs`

Under the repository's engine-first rule, **relational table ownership and local GPU/ANE inference checkpointing are separated at the sweep output boundary**:
1. **Local GPU/ANE inference checkpointing stays in `parquet_runner_v6.py`:** During a `FastGemma4Engine` + `Laya` ANE + two-phase `GPT-OSS-20B` sweep, `run_docmeta_parquet_sweep` streams local `part-NNNNN.parquet` shards via `.tmp` + `os.replace` and skips already-decoded `link_key_hex` keys on `--resume`. Spawning a native `docspec-rs` DataFusion process per decode chunk alongside a 24 GiB MLX/ANE working set on unified memory would add multi-GB RSS spikes without relational benefit.
2. **Lake ingestion, deduplication, and release publication belong exclusively to `docspec-rs`:** Completed DocMeta sidecar Parquets (`completed_no_llm.parquet` + sealed sweep outputs) must enter Iceberg lake tables or published release artifacts solely through `congress_api.lake.tables.append_rows` / `run_job` (`docspec-rs`), never through ad-hoc Python table merges.
