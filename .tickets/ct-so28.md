---
id: ct-so28
status: closed
deps: [ct-02x5]
links: []
created: 2026-11-22T19:53:26Z
type: task
priority: 2
assignee: mikewolfd
parent: ct-o7j0
tags: [docmeta, v7, training]
---
# DocMeta V7.3a: Clean-slate 10K+ 3-family corpus build, Quick Polish, Cleanlab/MiniLM audit & sealed qualification

Build, polish, and qualify the clean-slate V7.3a corpus (`10,500+` balanced rows across all `14` V7 genres + explicit hard-negative null strata) under one locked `codebook_v7.0`, audited post-hoc with 3rd-family review, Cleanlab Confident Learning, canonical grounding verification, authentic byte-identity (`saved_body_hex`/`link_key_hex`), and dual-mode TF-IDF + MiniLM decontamination against `sealed_temporal_2026` (`>= 500` docs, `0` hard leaks). Local Apple Silicon student SFT/DPO & 328K archive sweep live in split ticket `ct-pqi5` (V7.3b). Plan: `docs/plans/docmeta-v7-consulting-plan-20261122.md`; Release contract: `docs/plans/docmeta-v7-release-contract.md`.

## Acceptance Criteria

1) 10K+ balanced corpus strictly sealed (`--strict`) under `.cache/archive-release/docmeta-v7-corpus/sealed/` with Croissant 1.0 + DCAT-3 manifests having 1:1 Parquet column parity, `>= 150` docs per genre across all 14 genres, `0` canonical grounding errors, authentic `saved_body_hex`/`link_key_hex` identity (`null` where absent on legacy SSOT), Cleanlab OOF audit completed, and `0` unwaived/hard leakage against `sealed_temporal_2026` under TF-IDF + MiniLM decontamination. 2) Split V7.3b student ticket (`ct-pqi5`) tracks student training/sweep and unblocks `ct-rlw5`.


## Notes

**2026-11-23T04:01:10Z**

Launched V7.3 10,500-doc candidate pool & sharded 3-family corpus builder under .cache/archive-release/docmeta-v7-corpus/:
- Candidate manifest (candidate_manifest.json): 10,500 unique docs (3,698 SSOT + 6,802 mined archive, 980 from 2026 >= 700 target, sha256=907137557d06b7aeffbc570ba26f6da2d200e8ccd29d989cb390330892dd7e0a).
- Sealed shards: shard_0000.jsonl (250 docs: 230 auto_accept_gold, 19 checkeval_resolved, 1 deadlock_needs_owner) and shard_0001.jsonl (250 docs: 236 auto_accept_gold, 9 checkeval_resolved, 5 deadlock_needs_owner) = 500/10,500 sealed cleanly.
- Added --claude-effort and --specialist-families CLI/factory options (34/34 V7 tests pass) and switched live daemon to --workers 25 with core_triage across claude-opus-5-5 (--effort medium, also CheckEval arbiter) + gpt-6.2-sol (effort=medium) + gemini-4-neon-medium, and single final specialist extraction on claude only (claude-opus-5-5 --effort medium).
- Verified live Shard 3 cruising (doc=20/250 in task-7715.log; 122 upgraded cache completions with 0 errors; claude specialist avg ~16.9s vs ~52s multi-model Stage 2 previously).
- Resume command (idempotent): .venv/bin/python -m congress_docmeta.v7.factory.corpus_builder run --candidates .cache/archive-release/docmeta-v7-corpus/candidates_v7_3.jsonl --out-dir .cache/archive-release/docmeta-v7-corpus --workers 25 --timeout 120 --shard-size 250 --claude-model claude-opus-5-5 --claude-effort medium --codex-model gpt-6.2-sol --codex-reasoning medium --gemini-model gemini-4-neon-medium --specialist-families claude
- Seal command (after all 42 shards complete): .venv/bin/python -m congress_docmeta.v7.factory.corpus_builder seal --corpus-dir .cache/archive-release/docmeta-v7-corpus

**2026-11-23T18:49:17Z**

2026-11-23 Stripped B=16 relaunch (opus_low + sol_low, 50% UsageGuard):
- Preserved shard_0000..0017 (4,500 clean 3-family docs); removed 4 quota-corrupted shards (shard_0018..0021).
- Fixes in runners.py + corpus_builder.py: hoisted root $defs in build_batch_schema for CORE_TRIAGE and all 5 specialist schemas; moved empty_cwd to temp dir docmeta_v7_empty_cwd outside repo (3,027B vs 13,108B repo AGENTS.md in Codex rollouts); added per-batch stderr [batch] telemetry logging, UsageGuard.trip() fail-fast on invalid_json_schema (no silent B=1 fallback), and UsageGuard(require_telemetry=True) 2-call streak guard.
- Unit tests: 39 passed in packages/congress_docmeta/tests/v7/. Live B=4 smoke test (4 uncached shard_0018 docs): 4/4 Claude core (5.0%), 4/4 Codex core (6.0%), 4/4 Claude specialist (5.0%), auto_accept_gold=4.
- Launch command: .venv/bin/python -m congress_docmeta.v7.factory.corpus_builder run --candidates .cache/archive-release/docmeta-v7-corpus/candidates_v7_3.jsonl --out-dir .cache/archive-release/docmeta-v7-corpus --families claude,codex --specialist-families claude --batch-size 16 --specialist-batch-size 8 --workers 4 --timeout 240 --shard-size 250 --claude-model claude-opus-5-5 --claude-effort low --codex-model gpt-6.2-sol --codex-reasoning low --stripped-prefix --max-usage-pct 50.0
- Live daemon (task-8018) verified: Claude B=16 chunks 1..6 accepted 93/96 at usage_pct=5.0%; Codex B=16 chunks 1,3 accepted 32/32 at usage_pct=6.0%.

**2026-11-23T19:26:26Z**

2026-11-23 Full tool/skill/MCP/prompt strip + workers=8 relaunch (task-8141):
- Kept exact model tiers (claude-opus-5-5 --effort low, gpt-6.2-sol effort=low, service_tier="default", --max-usage-pct 50.0).
- Claude stripped flags (runners.py build_claude_command): added --disable-slash-commands and --agents '{}' alongside --strict-mcp-config --setting-sources '' (no --bare so OAuth works; slash_commands 55->0, skills 19->0, mcp_servers=0, tools=['StructuredOutput']).
- Codex stripped flags & isolated HOME/CODEX_HOME (runners.py build_codex_command + _prepare_stripped_codex_home): per-call temp HOME + CODEX_HOME symlinking only auth.json read-only, minimal config.toml (project_doc_max_bytes=0, web_search="disabled", service_tier="default", notify=[], mcp_servers={}, plugins={}, code_mode/shell_tool/unified_exec/apps/browser_use/computer_use/memories/multi_agent/goals/steer/plugins/hooks/skills disabled) + base_instructions.txt (upfront prompt ~31K -> ~5.8K tokens, 0 SkyComputerUseClient spawns). Updated _format_*_batch_prompt to forbid tool calls.
- Verification: pytest tests/v7/ -> 40 passed in 3.11s; B=16 stripped smoke check (16 uncached shard_0019 docs) -> Codex 16/16 in 110.1s (6.88s/doc vs 171.7-240s+ previously) at 7.0% usage, Claude 16/16 specialists at 6.0%, 16/16 resolved (12 auto_accept_gold, 4 checkeval_resolved).
- Relaunched task-8141 at --workers 8: shard_0019 Codex 7/7 chunks finished 106/106 accepted in <2m at 8.0% usage (zero timeouts).

**2026-11-23T23:47:05Z**

Hardest-32 29-model benchmark selected top fast 3-family ensemble: gpt-6.1-terra (low, 81.2% exact / 4.17s/doc), gemini-4-neon-low (stripped agy, 81.2% exact / 5.01s/doc), claude-opus-5-5 (low, #1 Status+Genre 90.6% / 3.48s/doc), Stage 2 claude B=8. Wired stripped single-turn agy (B<=12, <=110K chars, downstream Pydantic+grounding, UsageGuard telemetry_families=('claude','codex') + _AGY_QUOTA_ERR_RE) into corpus_builder.py/runners.py (46 V7 tests pass; 6-doc live smoke 6/6 auto_accept_gold at 13% usage). Launched 3-family daemon task-8532 over remaining shard_0029..0041 (3,250 docs) under --max-usage-pct 50.0; verified live batches for all 3 families (claude 7x 16/16, codex 6x 16/16, gemini 6x 11-12/12, rc=0, usage 13%).

**2026-11-24T02:53:03Z**

Initial base seal (`docmeta_v7_3.parquet`, 10,413 rows x 23 cols, `sha256=a93f1465962fbba62c71f4ea105ce327484eebf7e235b0ec55116a52ca805f01`): `total_processed=10,500`, `gold_count=10,413`, `deadlock_count=87`, `usable=10,246`, `budget_or_cost_estimate=129`, `cleanlab_oof_accuracy=0.9405` (`45` flagged), `minilm_checked=false` — superseded by strict polished re-seal below.

**2026-11-24T05:13:15Z**

Quick Polish + Astra/Fable Architecture Integration + Strict Sealed V7.3a Re-Seal (`seal_gates.passed = true`):
- **Scope Split:** Narrowed `ct-so28` to V7.3a corpus qualification; moved local Apple Silicon student SFT/DPO & 328K archive sweep to child ticket `ct-pqi5` (Owner Decision A2).
- **Quick Polish (`bulk_review` + `docmeta_v7_polish.py`):** Audited all `2,750` 2-family middle-shard docs (`shard_0018..0028`) with stripped `gemini-4-neon-low` (`2,651` confirmed, `10` flipped on 3-family+CheckEval adjudication), reviewed `87/87` deadlocks (`80` promoted: `78` 2-of-3 + `2` CheckEval-verified, leaving `7` true deadlocks), audited `44` Cleanlab flags (`1` flipped, `43` retained), mined `+49` top-up candidates yielding `+32` `budget_or_cost_estimate` (`129 -> 162`), and extracted `53/53` Stage 2 Claude specialist payloads (`usage_guard.tripped=false`, Claude `23.0%`).
- **Architecture Fixes & Fail-Closed Seal Metrics (`MANIFEST.json`, `docmeta_v7_3.parquet` 10,542 x 33, `sha256=fb371e5ecf93d962e9e34ebbbebf0af779a400592ff2552e807f874188c02544`):**
  - Totals: `10,549` processed, `10,542` gold (`99.93%`: `9,567` `auto_accept_gold`, `975` `checkeval_resolved`), `7` deadlocks (`0.07%`), `10,343` usable, `9,539` (`90.49%`) 3-family consensus (`801` 2-family, `202` 1-family), `10,200` single-teacher (`claude`) Stage-2 specialist silver.
  - All 14 genres `>= 150` (`budget_or_cost_estimate=162` min overall; per-split holdouts explicitly tracked: `dev_iter=1,237` has `budget_or_cost_estimate=24, oversights=13, ttf=22`; `sealed_temporal_2026=2,296` has `budget_or_cost_estimate=8, witness_testimony=162`, `train=7,009`).
  - Canonical grounding (`reconcile_and_validate_v7_payload` + `verify_grounded_extraction`): `10,542/10,542` verified with `0` errors after `60` deterministic repairs (`52` title_span alignment, `6` synthesized date_spans, `1` abstained ungrounded `doc_date`, `1` `issuer_org_span` alignment).
  - Source byte identity: `10,474/10,542` matched authentic `link_key_hex` & `saved_body_hex` (`68` legacy SSOT rows set to explicit `null`, `0` fabricated digests).
  - Cleanlab (5-fold TF-IDF over `10,343` usable docs): `oof_accuracy=0.9397`, `flagged_count=46` (`0.0044`).
  - Dual-mode Decontamination (`minilm_checked=true`, `all-MiniLM-L6-v2` offline + TF-IDF): `0` `exact_sha`, `0` `normalized_text_hash`, `0` `event_group_overlap`, `0` `ngram8`, `0` `ngram13`; `70` `tfidf_cosine` + `356` `minilm_cosine` template hits (`372/378` across distinct event dates/keys, plus `6` reviewed distinct-document waivers in `.cache/archive-release/docmeta-v7-corpus/polish/decontam_waivers.json`).
  - Croissant 1.0 (`7.3.0`, 33/33 column parity) & DCAT-3 validated cleanly; `git_provenance` stamped transparently (`git_head=8d04d9db...`, `git_dirty=true`, uncommitted per Owner Decision A3).
  - Unit suite: `54 passed in 2.01s` (`packages/congress_docmeta/tests/v7/`).
