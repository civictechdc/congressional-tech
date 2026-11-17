"""DocMeta validators, grammar router and sweep against the fast-gemma4 tokenizer, ANE and MLX backends.

Run by the `docmeta-model` lane. `REPO_ROOT` here is the fast-gemma4 checkout: it holds the validator artifacts,
the native runner and the build directory.
"""

from __future__ import annotations

import collections
import copy
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any

import pytest

pytest.importorskip("fast_gemma4", reason="needs the fast-gemma4 engine; run scripts/dev.py test docmeta-model")

import fast_gemma4  # noqa: E402
from congress_docmeta import (  # noqa: E402
    SCHEMA_V4_STR,
    AtomicOutputValidatorV6,
    PreDecodeGrammarRouterV6,
    build_doc_kind_set_schema_v6,
    per_doc_grammar_v6,
    run_docmeta_parquet_sweep,
    score_atomic_stdlib_v6,
    score_docmeta_anomalies_v6,
    surname_token_v6,
)
from congress_docmeta.cli import build_parser  # noqa: E402
from docmeta_test_support import VAL48_ARCHIVE_DIR, _auroc, _hw_lock, _load_docs8_pairs, _load_val48_records  # noqa: E402
from fast_gemma4.grammar import GrammarHelper  # noqa: E402
from fast_gemma4.paths import resolve_paths  # noqa: E402
from fast_gemma4.per_doc_grammar import SyncMatcher  # noqa: E402
from fast_gemma4.tokenizer import FastGemma4Tokenizer, VocabRemapper  # noqa: E402

REPO_ROOT = Path(fast_gemma4.__file__).resolve().parents[2]
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "atomic_validators"


def test_cli_and_parquet_runner_custom_codes_propagation(tmp_path: Path) -> None:
    """Verify `--atomic-verifier` CLI flag and custom `codes` propagation in `run_docmeta_parquet_sweep`."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    parser = build_parser()
    for mode_val in ("none", "laya-ane", "kev-0.8b", "both"):
        parsed = parser.parse_args(["docmeta-sweep", "in.parquet", "out.parquet", "--atomic-verifier", mode_val])
        assert parsed.atomic_verifier == mode_val

    paths = resolve_paths()
    tok = FastGemma4Tokenizer(paths.resolve_tokenizer_json())
    rem = VocabRemapper.load_or_build(paths.resolve_tokenizer_json(), paths.vocab_remap_npz)
    gh_std = GrammarHelper(tok, SCHEMA_V4_STR, rem.kept_old_ids, whitespace_flexible=False)
    up_len = len(gh_std.upfront_ff)

    valid_json_str = json.dumps(
        {
            "status": "usable",
            "text_quality": "native",
            "chamber": "house",
            "congress": 118,
            "committees": ["Committee on Science, Space, and Technology"],
            "primary_kind": "witness_statement",
            "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
            "composed_title": "Testimony of Jane Doe on Grid Reliability",
            "gist": "Jane Doe testifies on electric grid reliability.",
            "topics": ["electric grid"],
        },
        separators=(",", ":"),
    )
    gen_suffix_ids = tok.encode(valid_json_str, add_special_tokens=False)[up_len:]

    class _FakeEngine:
        def __init__(self) -> None:
            self.tokenizer = tok
            self.new_to_old = rem.kept_old_ids

        def run_rolling(self, **kwargs: Any) -> dict[str, Any]:
            n = len(kwargs["suf_ids_list"])
            gh = kwargs["gh"]
            for di in range(n):
                if hasattr(gh, "new_matcher_for_doc"):
                    gh.new_matcher_for_doc(di)
            return {
                "gen_toks": [list(gen_suffix_ids) for _ in range(n)],
                "prefill_sec": 0.01,
                "decode_sec": 0.01,
                "mask_fallbacks": 0,
                "llm_steps": 8,
                "ff_early14_steps": 1,
            }

    rows = []
    for i in range(2):
        lk = f"{i + 10:016x}"
        sb = f"{i + 10:064x}"
        rows.append(
            {
                "list_row": i,
                "link_key": bytes.fromhex(lk),
                "link_key_hex": lk,
                "doc_key": f"doc-{i:04d}",
                "saved_body": bytes.fromhex(sb),
                "saved_body_hex": sb,
                "effective_body_sha_hex": sb,
                "package_id": None,
                "rn": i,
                "disposition": "llm_queue",
                "v6_route": "deterministic_enriched_open_kind",
                "filename": f"HHRG-118-SY00-Wstate-DoeJ-202405{i + 10:02d}.pdf",
                "effective_format": "pdf",
                "text_source": "body_text_ssot_v12_head_tail_9000",
                "p12_raw_text": "Statement of Jane Doe before the House Committee on Science, Space, and Technology on electric grid reliability.",
                "p12_clean_text": "Statement of Jane Doe before the House Committee on Science, Space, and Technology on electric grid reliability.",
                "known_json": json.dumps({"congress": 118, "cmt": ["hssy00"], "chambers": ["house"]}),
                "locked_primary_kind": None,
                "grammar_lock_source": None,
                "lock_id": None,
                "rel_congress": 118,
                "rel_chamber": "house",
                "rel_committees": ["Committee on Science, Space, and Technology"],
                "rel_event_id": "ev1",
                "rel_event_date": "2024-05-15",
                "rel_event_title": "Electric Grid Reliability",
                "rel_event_type": "hearing",
                "rel_venue": None,
                "personas_seed_json": None,
                "det_refs": [],
                "det_short_titles": [],
                "det_fiscal_years": [],
                "usc_oracle_invalid_refs": [],
                "hsru_host_status": "not_hsru",
                "is_cover_roster_p12": False,
                "p3_toc_or_gavel_slice": None,
                "stapled_ttf_disclosure_json": None,
            }
        )

    in_pq = tmp_path / "in.parquet"
    out_pq = tmp_path / "out.parquet"
    pq.write_table(pa.Table.from_pylist(rows), in_pq)

    def _mock_atomic_verifier(clean_objs: Any, _chunk: Any) -> list[dict[str, Any]]:
        return [
            {
                "mode": "both",
                "score": 0.22 if idx == 0 else 0.91,
                "defect_score": 0.78 if idx == 0 else 0.09,
                "is_faithful": idx != 0,
                "escalate": idx == 0,
                "codes": ["atomic_committee_suspect", "atomic_gist_suspect"] if idx == 0 else [],
            }
            for idx in range(len(clean_objs))
        ]

    summary = run_docmeta_parquet_sweep(
        _FakeEngine(),
        in_pq,
        out_pq,
        chunk_rows=4,
        b_slots=2,
        use_ane_ring=False,
        external_verifier=_mock_atomic_verifier,
    )
    assert summary.docs_processed == 2
    assert summary.anomaly_flagged_docs == 1

    out_rows = pq.read_table(out_pq).to_pylist()
    r0_codes = out_rows[0]["anomaly_flags"]
    assert "atomic_committee_suspect" in r0_codes
    assert "atomic_gist_suspect" in r0_codes
    assert "external_verifier_flagged" in r0_codes
    assert out_rows[0]["needs_teacher_escalation"] is True
    assert out_rows[1]["needs_teacher_escalation"] is False




def test_async_stage1_ane_overlap_across_chunks_in_parquet_sweep(tmp_path: Path) -> None:
    """Prove `run_stage1_ane` executes on background thread concurrently with the next chunk's `engine.run_rolling`."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    paths = resolve_paths()
    tok = FastGemma4Tokenizer(paths.resolve_tokenizer_json())
    rem = VocabRemapper.load_or_build(paths.resolve_tokenizer_json(), paths.vocab_remap_npz)
    gh_std = GrammarHelper(tok, SCHEMA_V4_STR, rem.kept_old_ids, whitespace_flexible=False)
    up_len = len(gh_std.upfront_ff)

    valid_json_str = json.dumps(
        {
            "status": "usable",
            "text_quality": "native",
            "chamber": "house",
            "congress": 118,
            "committees": ["Committee on Science, Space, and Technology"],
            "primary_kind": "witness_statement",
            "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
            "composed_title": "Testimony of Jane Doe on Grid Reliability",
            "gist": "Jane Doe testifies on electric grid reliability.",
            "topics": ["electric grid"],
        },
        separators=(",", ":"),
    )
    gen_suffix_ids = tok.encode(valid_json_str, add_special_tokens=False)[up_len:]

    stage1_started = threading.Event()
    gpu_chunk1_entered_while_stage1_inflight = False
    stage1_threads_seen: list[str] = []

    class _OverlapEngine:
        def __init__(self) -> None:
            self.tokenizer = tok
            self.new_to_old = rem.kept_old_ids
            self.chunk_idx = 0

        def run_rolling(self, **kwargs: Any) -> dict[str, Any]:
            nonlocal gpu_chunk1_entered_while_stage1_inflight
            if self.chunk_idx == 1:
                # Wait briefly for Chunk 0's background ANE thread to signal it is mid-execution!
                if stage1_started.wait(timeout=2.0):
                    gpu_chunk1_entered_while_stage1_inflight = True
            self.chunk_idx += 1
            n = len(kwargs["suf_ids_list"])
            gh = kwargs["gh"]
            for di in range(n):
                if hasattr(gh, "new_matcher_for_doc"):
                    gh.new_matcher_for_doc(di)
            return {
                "gen_toks": [list(gen_suffix_ids) for _ in range(n)],
                "prefill_sec": 0.01,
                "decode_sec": 0.01,
                "mask_fallbacks": 0,
                "llm_steps": 6,
                "ff_early14_steps": 1,
            }

    class _AsyncStage1Verifier:
        supports_async_ane_stage1 = True

        def run_stage1_ane(self, clean_objs: Any, chunk: Any) -> dict[str, Any]:
            stage1_threads_seen.append(threading.current_thread().name)
            stage1_started.set()
            return {"clean_objs": clean_objs, "chunk": chunk}

        def finish_stage2(self, stage1: dict[str, Any]) -> list[dict[str, Any]]:
            return [
                {"score": 0.93, "defect_score": 0.07, "is_faithful": True, "escalate": False, "codes": []}
                for _ in stage1["clean_objs"]
            ]

        def __call__(self, clean_objs: Any, chunk: Any) -> list[dict[str, Any]]:
            return self.finish_stage2(self.run_stage1_ane(clean_objs, chunk))

    rows = []
    for i in range(6):
        lk = f"{i + 100:016x}"
        sb = f"{i + 100:064x}"
        rows.append(
            {
                "list_row": i,
                "link_key": bytes.fromhex(lk),
                "link_key_hex": lk,
                "doc_key": f"doc-async-{i:04d}",
                "saved_body": bytes.fromhex(sb),
                "saved_body_hex": sb,
                "effective_body_sha_hex": sb,
                "package_id": None,
                "rn": i,
                "disposition": "llm_queue",
                "v6_route": "deterministic_enriched_open_kind",
                "filename": f"HHRG-118-SY00-Wstate-DoeJ-202405{i + 10:02d}.pdf",
                "effective_format": "pdf",
                "text_source": "body_text_ssot_v12_head_tail_9000",
                "p12_raw_text": "Statement of Jane Doe before the House Committee on Science, Space, and Technology on electric grid reliability.",
                "p12_clean_text": "Statement of Jane Doe before the House Committee on Science, Space, and Technology on electric grid reliability.",
                "known_json": json.dumps({"congress": 118, "cmt": ["hssy00"], "chambers": ["house"]}),
                "locked_primary_kind": "witness_statement",
                "grammar_lock_source": "cover_lock",
                "lock_id": "wstate_lock",
                "rel_congress": 118,
                "rel_chamber": "house",
                "rel_committees": ["Committee on Science, Space, and Technology"],
                "rel_event_id": "ev1",
                "rel_event_date": "2024-05-15",
                "rel_event_title": "Electric Grid Reliability",
                "rel_event_type": "hearing",
                "rel_venue": None,
                "personas_seed_json": None,
                "det_refs": [],
                "det_short_titles": [],
                "det_fiscal_years": [],
                "usc_oracle_invalid_refs": [],
                "hsru_host_status": "not_hsru",
                "is_cover_roster_p12": False,
                "p3_toc_or_gavel_slice": None,
                "stapled_ttf_disclosure_json": None,
            }
        )

    in_pq = tmp_path / "async_in.parquet"
    out_pq = tmp_path / "async_out.parquet"
    pq.write_table(pa.Table.from_pylist(rows), in_pq)

    summary = run_docmeta_parquet_sweep(
        _OverlapEngine(),
        in_pq,
        out_pq,
        chunk_rows=2,
        b_slots=2,
        use_ane_ring=False,
        external_verifier=_AsyncStage1Verifier(),
    )
    assert summary.docs_processed == 6
    assert summary.chunks_written == 3
    assert summary.strict_v4_valid_docs == 6
    assert gpu_chunk1_entered_while_stage1_inflight is True
    assert len(stage1_threads_seen) == 3
    assert all(name == "docmeta-laya-ane-stage1" for name in stage1_threads_seen)
    out_tbl = pq.read_table(out_pq)
    assert out_tbl.num_rows == 6




def test_live_laya_ane_kev_mlx_and_both_validators_on_val48() -> None:
    """Run live `Laya-Typed-421M` ANE (`0` GPU ops), `W8` `Kev-0.8B` MLX, and `"both"` on `val_48` + `docs_8`."""
    if not (ARTIFACTS_DIR / "laya_typed" / "laya_typed_s512_w8.mlmodelc").exists():
        pytest.skip(f"Staged validator artifacts not present under {ARTIFACTS_DIR}")

    clean_objs, chunk_rows, y_doc_def, y_pers_def = _load_val48_records()
    d8_objs, d8_rows, d8_y = _load_docs8_pairs()

    # Simulate realistic `llm_queue_v6_2` grammar locks on the 24 docs whose `primary_kind` matches gold
    locked_rows = []
    for i, r in enumerate(chunk_rows):
        rc = dict(r)
        if y_doc_def[i] == 0 and i % 2 == 0:
            rc["locked_primary_kind"] = clean_objs[i].get("primary_kind")
        locked_rows.append(rc)

    with _hw_lock("pytest_atomic_validator_v6_val48"):
        # 1. Laya-Typed-421M Pure ANE (`laya-ane`: `S=256` + `S=512` buckets, `0` GPU ops)
        with AtomicOutputValidatorV6(mode="laya-ane", home=REPO_ROOT) as v_ane:
            assert v_ane.laya_backend is not None
            plans = v_ane.laya_backend.inspect_compute_plans()
            for bucket_tag, (ane_ops, gpu_ops, _cpu_ops) in plans.items():
                assert gpu_ops == 0, f"Expected 0 GPU ops on {bucket_tag}, got {plans}"
                assert ane_ops > 1000, f"Expected >1000 ANE ops on {bucket_tag}, got {plans}"

            t0 = time.perf_counter()
            res_ane = v_ane(clean_objs, chunk_rows)
            ane_ms = 1000.0 * (time.perf_counter() - t0) / len(clean_objs)

            v_ane.score_personas = False
            t0_doc = time.perf_counter()
            _ = v_ane(clean_objs, chunk_rows)
            ane_doc_only_ms = 1000.0 * (time.perf_counter() - t0_doc) / len(clean_objs)

            t0_lock = time.perf_counter()
            res_ane_locked = v_ane(clean_objs, locked_rows)
            ane_locked_ms = 1000.0 * (time.perf_counter() - t0_lock) / len(clean_objs)
            v_ane.score_personas = True

            # Verify pointwise batch-size invariance (single-doc score == batch score)
            single_0 = v_ane([clean_objs[0]], [chunk_rows[0]])[0]
            assert abs(single_0["defect_score"] - res_ane[0]["defect_score"]) < 1e-3

        ane_def = [float(d["defect_score"]) for d in res_ane]
        ane_locked_def = [float(d["defect_score"]) for d in res_ane_locked]
        ane_pers_def = [float(p) for d in res_ane for p in d["persona_defect_scores"]]
        assert len(ane_pers_def) == len(y_pers_def)
        auroc_ane = _auroc(y_doc_def, ane_def)
        auroc_ane_locked = _auroc(y_doc_def, ane_locked_def)
        auroc_ane_pers = _auroc(y_pers_def, ane_pers_def)
        print(
            f"[val_48 laya-ane] doc_only={ane_doc_only_ms:.2f} ms/doc | locked_doc={ane_locked_ms:.2f} ms/doc "
            f"| doc+personas={ane_ms:.2f} ms/doc | DocAUROC={auroc_ane:.4f} (locked={auroc_ane_locked:.4f}) "
            f"| PersonaAUROC={auroc_ane_pers:.4f}"
        )
        assert auroc_ane >= 0.92, f"Expected laya-ane DocAUROC >= 0.92, got {auroc_ane:.4f}"
        assert auroc_ane_locked >= 0.92, f"Expected lock-aware laya-ane DocAUROC >= 0.92, got {auroc_ane_locked:.4f}"
        assert auroc_ane_pers >= 0.72, f"Expected laya-ane PersonaAUROC >= 0.72, got {auroc_ane_pers:.4f}"

        # 2. Kev-0.8B r15 `W8` Metal MLX (`kev-0.8b`) on `val_48` + `docs_8` full-schema corruptions
        w8_path = ARTIFACTS_DIR / "kev_08b" / "model_w8.safetensors"
        assert w8_path.is_file(), f"Expected 8-bit Kev-0.8B weights at {w8_path}"
        assert w8_path.stat().st_size < 850 * 1024 * 1024  # ~764 MB vs 1,436 MB bf16

        with AtomicOutputValidatorV6(mode="kev-0.8b", home=REPO_ROOT, score_personas=False) as v_kev:
            assert v_kev.kev_backend is not None
            assert v_kev.kev_backend.quant_mode == "w8"
            t0 = time.perf_counter()
            res_kev = v_kev(clean_objs, chunk_rows)
            kev_ms = 1000.0 * (time.perf_counter() - t0) / len(clean_objs)

            single_k0 = v_kev([clean_objs[0]], [chunk_rows[0]])[0]
            assert abs(single_k0["defect_score"] - res_kev[0]["defect_score"]) < 1e-3

            res_d8 = v_kev(d8_objs, d8_rows)

        kev_def = [float(d["defect_score"]) for d in res_kev]
        auroc_kev = _auroc(y_doc_def, kev_def)
        auroc_d8 = _auroc(d8_y, [float(d["defect_score"]) for d in res_d8])
        print(f"[val_48 kev-0.8b W8] {kev_ms:.2f} ms/doc | val_48 DocAUROC={auroc_kev:.4f} | docs_8 FullSchemaAUROC={auroc_d8:.4f}")
        assert auroc_kev >= 0.94, f"Expected W8 kev-0.8b DocAUROC >= 0.94, got {auroc_kev:.4f}"
        assert auroc_d8 >= 0.95, f"Expected W8 kev-0.8b docs_8 FullSchemaAUROC >= 0.95, got {auroc_d8:.4f}"

        # 3. Combined ANE + `W8` MLX (`both`: full ensemble & two-sided gray-zone cascade)
        with AtomicOutputValidatorV6(mode="both", home=REPO_ROOT, cascade=False) as v_both:
            t0 = time.perf_counter()
            res_both = v_both(clean_objs, chunk_rows)
            both_ms = 1000.0 * (time.perf_counter() - t0) / len(clean_objs)

            v_both.cascade = True
            t1 = time.perf_counter()
            res_casc = v_both(clean_objs, chunk_rows)
            casc_ms = 1000.0 * (time.perf_counter() - t1) / len(clean_objs)

            # Also measure Stage-2-only latency (when Stage-1 ANE already ran asynchronously behind Gemma-4 GPU!)
            s1_pre = v_both.run_stage1_ane(clean_objs, locked_rows)
            t2 = time.perf_counter()
            res_stage2_only = v_both.finish_stage2(s1_pre)
            stage2_gpu_ms = 1000.0 * (time.perf_counter() - t2) / len(clean_objs)

        both_def = [float(d["defect_score"]) for d in res_both]
        casc_def = [float(d["defect_score"]) for d in res_casc]
        s2_def = [float(d["defect_score"]) for d in res_stage2_only]
        auroc_both = _auroc(y_doc_def, both_def)
        auroc_casc = _auroc(y_doc_def, casc_def)
        auroc_s2 = _auroc(y_doc_def, s2_def)
        gpu_skipped_frac = sum(1 for d in res_casc if d["kev_score"] is None) / float(len(res_casc))
        print(
            f"[val_48 both] ensemble={both_ms:.2f} ms/doc (AUROC={auroc_both:.4f}) | "
            f"sync_cascade={casc_ms:.2f} ms/doc (AUROC={auroc_casc:.4f}, GPU skipped={100.0 * gpu_skipped_frac:.1f}%) | "
            f"async_stage2_gpu_only={stage2_gpu_ms:.2f} ms/doc (AUROC={auroc_s2:.4f})"
        )
        assert auroc_both >= 0.94, f"Expected both DocAUROC >= 0.94, got {auroc_both:.4f}"
        assert auroc_casc >= 0.95, f"Expected cascade DocAUROC >= 0.95, got {auroc_casc:.4f}"
        assert auroc_s2 >= 0.95, f"Expected async stage2 DocAUROC >= 0.95, got {auroc_s2:.4f}"
        assert gpu_skipped_frac >= 0.55, f"Expected two-sided cascade to skip >=55% GPU calls, got {gpu_skipped_frac:.2%}"

        for item in res_both:
            assert set(
                ("score", "defect_score", "is_faithful", "escalate", "laya_score", "kev_score", "persona_defect_scores", "flagged_fields", "codes")
            ).issubset(item.keys())
            assert item["is_faithful"] is (not item["escalate"])
            if item["escalate"]:
                assert item["score"] < 0.50
                assert len(item["codes"]) >= 1




def test_v63_grammar_router_ane_set_locks_and_persona_role_repair() -> None:
    """Verify V6.3 Pre-Decode Grammar Router (`fast` + `ane`), multi-kind `llguidance` set locks, and ANE `Choice(16)` role repair."""
    router_npz = ARTIFACTS_DIR / "router_v63_linear.npz"
    if not router_npz.is_file():
        pytest.skip(f"V6.3 router artifacts not present at {router_npz}")

    # 1. CLI flags & multi-kind `per_doc_grammar_v6` set schema compilation
    parser = build_parser()
    for gr_mode in ("none", "fast", "ane"):
        parsed = parser.parse_args(
            ["docmeta-sweep", "in.parquet", "out.parquet", "--grammar-router", gr_mode, "--repair-persona-roles"]
        )
        assert parsed.grammar_router == gr_mode
        assert parsed.repair_persona_roles is True

    set_schema = build_doc_kind_set_schema_v6(["oversight_letter", "external_submission_letter"])
    assert set_schema["properties"]["status"]["enum"] == ["usable"]
    assert set_schema["properties"]["primary_kind"]["enum"] == ["oversight_letter", "external_submission_letter"]

    paths = resolve_paths()
    tok = FastGemma4Tokenizer(paths.resolve_tokenizer_json())
    rem = VocabRemapper.load_or_build(paths.resolve_tokenizer_json(), paths.vocab_remap_npz)
    gh_std = GrammarHelper(tok, SCHEMA_V4_STR, rem.kept_old_ids, whitespace_flexible=False)
    gh_set = per_doc_grammar_v6(
        gh_std,
        doc_order=[0],
        doc_target_kinds={0: "external_submission_letter|oversight_letter"},
        sync_ff_with_std=True,
    )
    m_set = gh_set.new_matcher()
    assert isinstance(m_set, SyncMatcher)

    # 2. Evaluate `PreDecodeGrammarRouterV6` (`fast` and `ane`) on blind `val_48` + `docs_8` (56 docs, 0 training overlap!)
    gold48_raw = json.loads((VAL48_ARCHIVE_DIR / "lookups_and_gold" / "eval_val48_v4_gold.json").read_text(encoding="utf-8"))
    gold8_raw = json.loads((VAL48_ARCHIVE_DIR / "lookups_and_gold" / "eval_docs8_v4_gold.json").read_text(encoding="utf-8"))
    eval_rows: list[dict[str, Any]] = []
    eval_gold_kinds: list[str | None] = []
    for r in gold48_raw + gold8_raw:
        eval_rows.append(
            {
                "filename": r.get("filename", ""),
                "known": r.get("known", "<NONE>"),
                "p12_raw_text": r["text"] or "",
            }
        )
        g = r["gold"]
        eval_gold_kinds.append(g.get("primary_kind") if g.get("status") == "usable" else None)

    with _hw_lock("pytest_v63_router_and_role_repair"):
        with PreDecodeGrammarRouterV6(mode="fast", home=REPO_ROOT) as r_fast:
            t0 = time.perf_counter()
            out_fast = r_fast.route_chunk(eval_rows)
            fast_ms = 1000.0 * (time.perf_counter() - t0) / len(eval_rows)

        with AtomicOutputValidatorV6(mode="laya-ane", home=REPO_ROOT) as v_ane:
            # Share `laya_backend` with `PreDecodeGrammarRouterV6(mode="ane")` (`0` extra memory!)
            with PreDecodeGrammarRouterV6(
                mode="ane", home=REPO_ROOT, shared_laya_backend=v_ane.laya_backend
            ) as r_ane:
                t1 = time.perf_counter()
                out_ane = r_ane.route_chunk(eval_rows)
                ane_r_ms = 1000.0 * (time.perf_counter() - t1) / len(eval_rows)

            # Evaluate pure-ANE `laya-ane` on `docs_8` full-schema corruptions after V6.3 distillation!
            d8_objs, d8_rows, d8_y = _load_docs8_pairs()
            res_d8_ane = v_ane(d8_objs, d8_rows)
            auroc_d8_ane = _auroc(d8_y, [float(d["defect_score"]) for d in res_d8_ane])
            print(f"[docs_8 distilled laya-ane] FullSchemaAUROC={auroc_d8_ane:.4f}")
            assert auroc_d8_ane >= 0.85, f"Expected distilled laya-ane docs_8 AUROC >= 0.85, got {auroc_d8_ane:.4f}"

            # 3. Verify live ANE `Choice(16)` `repair_suspect_personas` repairs misroled human actors & ignores buildings!
            letter_objs = [
                {
                    "status": "usable",
                    "text_quality": "native",
                    "congress": 118,
                    "primary_kind": "witness_invitation",
                    "personas": [
                        {"name": "Michael Brey", "role": "chair", "entity_type": "non_gov_person"},
                        {"name": "Rayburn House Office Building", "role": "witness", "entity_type": "organization"},
                    ],
                    "correspondence_flow": "committee_to_witness",
                    "composed_title": "Invitation Letter to Michael Brey",
                    "gist": "Committee invites Michael Brey to testify.",
                    "topics": ["oversight"],
                }
            ]
            letter_rows = [
                {
                    "filename": "invite_brey.pdf",
                    "p12_clean_text": (
                        "Committee on Energy and Commerce\nJune 4, 2024\n"
                        "Dear Mr. Michael Brey:\n"
                        "On behalf of the Committee, we cordially invite you to testify as a witness at our hearing.\n"
                        "Sincerely,\nChairman Brett Guthrie"
                    ),
                }
            ]
            rep_verdicts = v_ane(letter_objs, letter_rows)
            repairs = v_ane.repair_suspect_personas(
                letter_objs, letter_rows, rep_verdicts, min_defect=0.45, min_prob=0.45
            )
            print(f"[ANE Choice(16) Persona Role Repairs] {repairs}")
            assert any(r["name"] == "Michael Brey" and r["new_role"] in ("recipient", "witness") for r in repairs)
            # Non-person building decoy must NEVER be 'role-repaired'
            assert all(r["name"] != "Rayburn House Office Building" for r in repairs)

    # Check router lock precision & set coverage on blind `val_48 + docs_8`
    for tag, out_r, ms_r in (("fast", out_fast, fast_ms), ("ane", out_ane, ane_r_ms)):
        lock1_hits = 0
        lock1_tot = 0
        set_hits = 0
        set_tot = 0
        for gk, dec in zip(eval_gold_kinds, out_r):
            ls = dec["lock_spec"]
            if ls is None or gk is None:
                continue
            allowed = ls.split("|")
            set_tot += 1
            if gk in allowed:
                set_hits += 1
            if len(allowed) == 1:
                lock1_tot += 1
                if gk == allowed[0]:
                    lock1_hits += 1
        prec1 = (lock1_hits / lock1_tot) if lock1_tot else 1.0
        cov_set = (set_hits / set_tot) if set_tot else 1.0
        print(
            f"[val_48+docs_8 router={tag}] {ms_r:.2f} ms/doc | locked_or_narrowed={set_tot}/{len(eval_rows)} "
            f"| 1-kind prec={prec1:.3f} ({lock1_hits}/{lock1_tot}) | set_cov={cov_set:.3f} ({set_hits}/{set_tot})"
        )
        assert set_tot >= 10
        assert cov_set >= 0.88, f"Expected router={tag} set coverage >= 0.88 on blind eval, got {cov_set:.3f}"
