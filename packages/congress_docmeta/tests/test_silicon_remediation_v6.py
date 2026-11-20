"""Offline unit tests for Shard 6 Apple Silicon orchestration, memory lifecycle, preflight, and manifest fixes."""

from __future__ import annotations

import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import types
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_docmeta import (
    VALIDATORS_MANIFEST_NAME,
    AtomicOutputValidatorV6,
    PreDecodeGrammarRouterV6,
    build_validators_manifest,
    check_r8_dependencies,
    clear_mlx_wave_cache,
    escalate_anomalies_gpt_oss,
    format_chat_no_thinking,
    mlx_wired_limit_scope,
    run_docmeta_parquet_sweep,
    run_silicon_preflight,
    unload_engine_memory,
    verify_validators_manifest,
    write_validators_manifest,
)
from congress_docmeta import atomic_validator_v6, cli, eval_blind, grammar_router_ane_v6, parquet_runner_v6
from congress_docmeta import silicon_runtime_v6

PKG_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PKG_ROOT / "src"


def _install_fake_mlx(monkeypatch: pytest.MonkeyPatch, *, max_rec: int = 32 << 30, initial_cache_limit: int = 16 << 30) -> types.SimpleNamespace:
    state = types.SimpleNamespace(
        wired_limit=0,
        wired_history=[],
        cache_limit=initial_cache_limit,
        cache_limit_history=[],
        cache_memory=512 << 20,
        clear_calls=0,
        version="0.32.4",
    )

    def set_wired_limit(val: int) -> int:
        prev = state.wired_limit
        state.wired_limit = int(val)
        state.wired_history.append(int(val))
        return prev

    def set_cache_limit(val: int) -> int:
        prev = state.cache_limit
        state.cache_limit = int(val)
        state.cache_limit_history.append(int(val))
        return prev

    def get_cache_memory() -> int:
        return state.cache_memory

    def clear_cache() -> None:
        state.clear_calls += 1
        state.cache_memory = 0

    fake_mx = types.ModuleType("mlx.core")
    fake_mx.__version__ = state.version  # type: ignore[attr-defined]
    fake_mx.device_info = lambda: {"max_recommended_working_set_size": max_rec}  # type: ignore[attr-defined]
    fake_mx.set_wired_limit = set_wired_limit  # type: ignore[attr-defined]
    fake_mx.set_cache_limit = set_cache_limit  # type: ignore[attr-defined]
    fake_mx.get_cache_memory = get_cache_memory  # type: ignore[attr-defined]
    fake_mx.clear_cache = clear_cache  # type: ignore[attr-defined]

    fake_mlx_pkg = types.ModuleType("mlx")
    fake_mlx_pkg.core = fake_mx  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mlx", fake_mlx_pkg)
    monkeypatch.setitem(sys.modules, "mlx.core", fake_mx)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, _orig=importlib.util.find_spec: object() if name in ("mlx", "mlx.core") else _orig(name))
    return state


def _install_fake_fast_gemma4_grammar(monkeypatch: pytest.MonkeyPatch) -> None:
    fg4_pkg = types.ModuleType("fast_gemma4")
    fg4_grammar = types.ModuleType("fast_gemma4.grammar")

    class _FakeGrammarHelper:
        def __init__(self, tok: Any, schema_str: str, new_to_old: Any, whitespace_flexible: bool = False) -> None:
            self.upfront_ff: list[int] = []
            self.schema_str = schema_str

    fg4_grammar.GrammarHelper = _FakeGrammarHelper  # type: ignore[attr-defined]
    fg4_pdg = types.ModuleType("fast_gemma4.per_doc_grammar")
    fg4_pdg.compute_rolling_doc_order = lambda suf_ids, **_: list(range(len(suf_ids)))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fast_gemma4", fg4_pkg)
    monkeypatch.setitem(sys.modules, "fast_gemma4.grammar", fg4_grammar)
    monkeypatch.setitem(sys.modules, "fast_gemma4.per_doc_grammar", fg4_pdg)


class _ByteTokenizer:
    def apply_chat_template(self, msgs: list[dict[str, str]], *, tokenize: bool = False, add_generation_prompt: bool = True, enable_thinking: bool = True) -> str:
        assert enable_thinking is False, "Expected explicit enable_thinking=False!"
        return msgs[0]["content"]

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return list(text.encode("utf-8"))[:256]

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
        return bytes(int(x) & 0xFF for x in ids).decode("utf-8", errors="ignore")


def _sample_valid_doc(gist: str = "Jane Doe testifies on electric grid reliability.") -> dict[str, Any]:
    return {
        "status": "usable",
        "text_quality": "native",
        "chamber": "house",
        "congress": 118,
        "committees": ["Committee on Science, Space, and Technology"],
        "primary_kind": "witness_statement",
        "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
        "composed_title": "Testimony of Jane Doe on Grid Reliability",
        "gist": gist,
        "topics": ["electric grid"],
    }


def _sample_queue_rows(n: int = 4) -> list[dict[str, Any]]:
    rows = []
    for i in range(n):
        lk = f"{i + 1:016x}"
        sb = f"{i + 1:064x}"
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
    return rows


def test_silicon_runtime_stdlib_isolation() -> None:
    code = (
        f"import sys; sys.path.insert(0, {str(SRC_DIR)!r})\n"
        "import congress_docmeta.silicon_runtime_v6 as sr\n"
        "for banned in ('mlx', 'numpy', 'pyarrow', 'jsonschema', 'usaddress'):\n"
        "    assert banned not in sys.modules, f'Unexpected import: {banned}'\n"
        "assert sr.parse_semver('26.6') == (26, 6)\n"
    )
    proc = subprocess.run(["/usr/bin/python3", "-B", "-I", "-S", "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_mlx_wired_limit_scope_and_wave_cache_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exception propagation when mlx is absent must never hit generator-didn't-stop
    with pytest.raises(ValueError, match="no_mlx_boom"):
        with mlx_wired_limit_scope() as applied_no_mlx:
            assert applied_no_mlx is None
            raise ValueError("no_mlx_boom")

    state = _install_fake_mlx(monkeypatch, max_rec=36 << 30)
    with mlx_wired_limit_scope() as applied:
        assert applied == 36 << 30
        assert state.wired_limit == 36 << 30
    assert state.wired_limit == 0
    assert state.wired_history == [36 << 30, 0]

    # Must restore wired limit even when body raises
    with pytest.raises(RuntimeError, match="boom"):
        with mlx_wired_limit_scope():
            assert state.wired_limit == 36 << 30
            raise RuntimeError("boom")
    assert state.wired_limit == 0

    # Wave cache clears only above threshold unless force=True
    state.cache_memory = 128 << 20
    assert clear_mlx_wave_cache(256) is False
    state.cache_memory = 400 << 20
    assert clear_mlx_wave_cache(256) is True
    assert state.clear_calls == 1
    assert clear_mlx_wave_cache(256, force=True) is True
    assert state.clear_calls == 2


def test_silicon_preflight_checks_os_mlx_tf32_ram_and_r8(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCMETA_NO_PREFLIGHT_WARN", raising=False)
    monkeypatch.delenv("FAST_SILICON_NO_HW_WARN", raising=False)
    buf = io.StringIO()
    res = run_silicon_preflight(
        escalate_gpt_oss=True,
        require_r8_deps=True,
        stream=buf,
        env_override={
            "system": "Darwin",
            "machine": "arm64",
            "os_version": "26.1",
            "mlx_version": "0.31.0",
            "mlx_enable_tf32": "0",
            "mlx_metal_no_nax": "1",
            "mem_gb": 24,
            "missing_r8_deps": [],
            "r8_deps_ok": True,
        },
    )
    warns = res["warnings"]
    assert any("macOS 26.1 < 26.2" in w for w in warns)
    assert any("mlx==0.31.0 < 0.32.4" in w for w in warns)
    assert any("MLX_ENABLE_TF32=0" in w for w in warns)
    assert any("MLX_METAL_NO_NAX=1" in w for w in warns)
    assert any("24 GiB (< 32 GiB)" in w for w in warns)
    assert "PREFLIGHT WARNING" in buf.getvalue()

    # Missing R8 deps MUST fail loudly when require_r8_deps=True
    with pytest.raises(RuntimeError, match="usaddress==0.5.14"):
        run_silicon_preflight(
            require_r8_deps=True,
            env_override={"system": "Darwin", "mem_gb": 48, "missing_r8_deps": ["usaddress==0.5.14"]},
        )

    # Current congressional-tech/.venv has all R8 deps installed cleanly
    assert check_r8_dependencies(strict=True) == []


def test_format_chat_no_thinking_explicit_flag() -> None:
    seen: list[dict[str, Any]] = []

    class _HfTok:
        def apply_chat_template(self, msgs: Any, *, tokenize: bool = False, add_generation_prompt: bool = True, enable_thinking: bool = True) -> str:
            seen.append({"enable_thinking": enable_thinking, "tokenize": tokenize, "add_generation_prompt": add_generation_prompt})
            return f"think={enable_thinking}:{msgs[0]['content']}"

    out = format_chat_no_thinking(_HfTok(), [{"role": "user", "content": "hello"}])
    assert out == "think=False:hello"
    assert seen == [{"enable_thinking": False, "tokenize": False, "add_generation_prompt": True}]

    class _LegacyTok:
        def apply_chat_template(self, msgs: Any, *, tokenize: bool = False, add_generation_prompt: bool = True) -> str:
            return f"legacy:{msgs[0]['content']}"

    assert format_chat_no_thinking(_LegacyTok(), [{"role": "user", "content": "hi"}]) == "legacy:hi"


def test_atomic_validator_defaults_cache_guard_single_build_and_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    state = _install_fake_mlx(monkeypatch, initial_cache_limit=512 << 20)
    # Build minimal synthetic validator artifact directory and pin its manifest
    (tmp_path / "laya_typed").mkdir(parents=True)
    (tmp_path / "kev_08b").mkdir(parents=True)
    (tmp_path / "validator_v63_calibration.json").write_text(json.dumps({"version": "v6_3"}), encoding="utf-8")
    (tmp_path / "router_v63_calibration.json").write_text(json.dumps({"version": "v6_3"}), encoding="utf-8")
    (tmp_path / "laya_typed" / "rl_agent_config.json").write_text(json.dumps({"model_name": "test"}), encoding="utf-8")

    manifest_p = write_validators_manifest(tmp_path, bundle_version="v6_3")
    assert manifest_p == tmp_path / VALIDATORS_MANIFEST_NAME
    v_ok = verify_validators_manifest(tmp_path, mode=True)
    assert v_ok["verified"] is True and v_ok["checked_files"] == 3

    # Tampering with a pinned artifact MUST raise ValueError immediately
    (tmp_path / "laya_typed" / "rl_agent_config.json").write_text(json.dumps({"model_name": "tampered"}), encoding="utf-8")
    with pytest.raises(ValueError, match="size mismatch|sha256 mismatch"):
        verify_validators_manifest(tmp_path, mode="if_present")

    # Restore valid manifest for constructor test
    (tmp_path / "laya_typed" / "rl_agent_config.json").write_text(json.dumps({"model_name": "test"}), encoding="utf-8")
    write_validators_manifest(tmp_path, bundle_version="v6_3")

    seen_kev_batch: list[int] = []

    class _FakeKev:
        def __init__(self, kev_dir: Path, *, quant_mode: str = "auto", batch_docs: int = 1) -> None:
            seen_kev_batch.append(batch_docs)
            # Simulate legacy Kev08bMlxBackend leaking a 1 GiB global cache limit!
            import mlx.core as mx
            mx.set_cache_limit(1 << 30)

        def close(self) -> None:
            pass

    class _FakeLaya:
        def __init__(self, laya_dir: Path, dylib_p: Path, *, pipe_depth: int = 4) -> None:
            self.encoded: list[tuple[dict[str, Any], dict[str, Any]]] = []

        def encode_item(self, st: dict[str, Any], q: dict[str, Any]) -> dict[str, Any]:
            self.encoded.append((st, q))
            return {"q": q["id"]}

        def score_noul_batch(self, encs: list[dict[str, Any]]) -> list[float]:
            return [0.9] * len(encs)

        def close(self) -> None:
            pass

    fdm_mod = types.ModuleType("fast_decision_models")
    fdm_mod.Kev08bMlxBackend = _FakeKev  # type: ignore[attr-defined]
    fdm_mod.LayaAneBackend = _FakeLaya  # type: ignore[attr-defined]
    fdm_paths = types.ModuleType("fast_decision_models.paths")
    fdm_paths.ensure_laya_dylib = lambda: tmp_path / "liblaya.dylib"  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fast_decision_models", fdm_mod)
    monkeypatch.setitem(sys.modules, "fast_decision_models.paths", fdm_paths)

    # Default kev_batch_docs must be 8, and 1 GiB cache limit leak must be capped back to 256 MiB and restored on close!
    with AtomicOutputValidatorV6(mode="both", artifacts_dir=tmp_path, verify_manifest=True) as val:
        assert seen_kev_batch == [8]
        assert val.kev_batch_docs == 8
        assert state.cache_limit == 256 << 20  # Leaked 1 GiB immediately capped back to 256 MiB!

        # Verify run_stage1_ane calls build_atomic_doc_questions_v6 ONCE per doc (not twice!)
        orig_build = atomic_validator_v6.build_atomic_doc_questions_v6
        build_calls = 0

        def _counting_build(*a: Any, **kw: Any) -> Any:
            nonlocal build_calls
            build_calls += 1
            return orig_build(*a, **kw)

        monkeypatch.setattr(atomic_validator_v6, "build_atomic_doc_questions_v6", _counting_build)
        doc = _sample_valid_doc()
        doc["correspondence_flow"] = "external_to_committee"
        row = {
            "filename": "letter.pdf",
            "p12_clean_text": "Committee on Science, Space, and Technology hearing statement by Jane Doe. " * 40,
        }
        s1 = val.run_stage1_ane([doc], [row])
        assert build_calls == 1
        assert 0 in s1["laya_field_probs"]
    # Prior cache limit (512 MiB) restored cleanly on close()
    assert state.cache_limit == 512 << 20


def test_grammar_router_reuses_pmetas_without_re_stripping_html(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("Should not re-run HTML detection when pmeta already has clean_text_v6!")

    monkeypatch.setattr(grammar_router_ane_v6, "infer_is_html_v6", _boom)
    row = {
        "filename": "page.html",
        "p12_raw_text": "<html><body><script>bad()</script><p>Hearing</p></body></html>",
    }
    pmeta = {
        "clean_text_v6": "Clean precomputed hearing text",
        "known_dict": {"congress": 118},
        "is_html": True,
    }
    fn, kn_str, raw_txt, clean_txt = PreDecodeGrammarRouterV6._extract_row_fields(row, pmeta)
    assert fn == "page.html"
    assert '"congress":118' in kn_str
    assert "<html>" in raw_txt
    assert clean_txt == "Clean precomputed hearing text"


def test_escalate_anomalies_gpt_oss_wires_k_and_enable_thinking() -> None:
    seen_calls: list[dict[str, Any]] = []
    doc_bad_gist = _sample_valid_doc(gist="HALLUCINATED WRONG GIST")
    doc_good_gist = _sample_valid_doc(gist="Jane Doe testifies on electric grid reliability.")

    class _Item:
        def __init__(self, obj: dict[str, Any]) -> None:
            self.parsed = obj
            self.text = json.dumps(obj, separators=(",", ":"))

    class _MockTeacher:
        def generate_batch(
            self,
            prompts: list[str],
            *,
            per_doc_grammars: Any = None,
            temperature: float = 0.0,
            seed: int = 42,
            enable_thinking: bool = True,
            **_kw: Any,
        ) -> Any:
            seen_calls.append({"temperature": temperature, "seed": seed, "enable_thinking": enable_thinking})
            # Sample 0 (greedy) hallucinates; sample 1 succeeds!
            chosen = doc_bad_gist if len(seen_calls) == 1 else doc_good_gist
            return types.SimpleNamespace(items=[_Item(chosen) for _ in prompts])

    def _verifier(cands: Any, _rows: Any) -> list[dict[str, Any]]:
        return [
            {
                "score": 0.1 if "HALLUCINATED" in c.get("gist", "") else 0.95,
                "defect_score": 0.9 if "HALLUCINATED" in c.get("gist", "") else 0.05,
                "is_faithful": "HALLUCINATED" not in c.get("gist", ""),
                "escalate": "HALLUCINATED" in c.get("gist", ""),
                "codes": ["atomic_gist_suspect"] if "HALLUCINATED" in c.get("gist", "") else [],
            }
            for c in cands
        ]

    cur_objs = [_sample_valid_doc(gist="Old weak gist")]
    cur_texts = [json.dumps(cur_objs[0], separators=(",", ":"))]
    cur_anoms = [{"has_anomaly": True, "escalate_to_teacher": True, "anomaly_score": 1.5, "anomaly_codes": ["atomic_gist_suspect"]}]
    cur_vs = [{"score": 0.2, "defect_score": 0.8, "is_faithful": False, "escalate": True, "codes": ["atomic_gist_suspect"]}]
    rows = _sample_queue_rows(1)
    pmetas = [{"known_dict": {"congress": 118}, "p12_lines": rows[0]["p12_clean_text"], "tier1_target_kind": None}]

    esc_n, acc_n, backups = escalate_anomalies_gpt_oss(
        _MockTeacher(),
        flagged_indices=[0],
        prompts_user_content=None,  # tests lazy prompt fallback too!
        rows=rows,
        pmetas=pmetas,
        current_objs=cur_objs,
        current_texts=cur_texts,
        current_anomalies=cur_anoms,
        external_verifier=_verifier,
        current_verdicts=cur_vs,
        k=2,
    )
    assert esc_n == 1 and acc_n == 1 and 0 in backups
    assert len(seen_calls) == 2
    assert seen_calls[0]["temperature"] == 0.0 and seen_calls[1]["temperature"] == 0.25
    assert all(c["enable_thinking"] is False for c in seen_calls)
    assert cur_objs[0]["gist"] == "Jane Doe testifies on electric grid reliability."


def test_two_phase_pass2_unloads_pass1_before_loading_gpt_oss_and_lazy_v4_prompts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_fast_gemma4_grammar(monkeypatch)
    _install_fake_mlx(monkeypatch)
    monkeypatch.setenv("DOCMETA_NO_PREFLIGHT_WARN", "1")

    tok = _ByteTokenizer()
    valid_doc = _sample_valid_doc()
    events: list[str] = []

    class _TrackableGemma4Engine:
        def __init__(self) -> None:
            self.tokenizer = tok
            self.new_to_old = list(range(256))
            self.model = object()
            self._w_emb = [1, 2, 3]
            self._w_pli14 = [4, 5, 6]
            self._prefix_cache = {"k": "v"}
            self.ane_ring_bundle = None

        def run_rolling(self, **kwargs: Any) -> dict[str, Any]:
            events.append("gemma4_run_rolling")
            n = len(kwargs["suf_ids_list"])
            return {
                "gen_toks": [tok.encode(json.dumps(valid_doc, separators=(",", ":"))) for _ in range(n)],
                "prefill_sec": 0.01,
                "decode_sec": 0.01,
                "mask_fallbacks": 0,
                "llm_steps": n,
                "ff_early14_steps": 0,
            }

        def close(self) -> None:
            events.append("gemma4_close")

    upgraded_doc = _sample_valid_doc(gist="Upgraded faithful summary by GPT-OSS Pass-2.")

    class _FakeGptOssEngine:
        def __init__(self, *, model_dir: Any = None, warmup: bool = True) -> None:
            events.append("gpt_oss_init")

        def generate_batch(self, prompts: list[str], *, per_doc_grammars: Any = None, enable_thinking: bool = True, **_: Any) -> Any:
            assert enable_thinking is False
            events.append("gpt_oss_generate")
            return types.SimpleNamespace(
                items=[types.SimpleNamespace(parsed=upgraded_doc, text=json.dumps(upgraded_doc, separators=(",", ":"))) for _ in prompts]
            )

        def close(self) -> None:
            events.append("gpt_oss_close")

    fgpt_mod = types.ModuleType("fast_gpt_oss")
    fgpt_mod.FastGptOssEngine = _FakeGptOssEngine  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fast_gpt_oss", fgpt_mod)

    in_pq = tmp_path / "in.parquet"
    out_pq = tmp_path / "out.parquet"
    pq.write_table(pa.Table.from_pylist(_sample_queue_rows(4)), in_pq)

    # 1. Verify lazy V4 prompt formatting: compact wire + escalate_gpt_oss=False calls build_prompt_v4 ZERO times!
    v4_calls = 0
    orig_v4 = parquet_runner_v6.build_prompt_v4

    def _spy_v4(*a: Any, **kw: Any) -> str:
        nonlocal v4_calls
        v4_calls += 1
        return orig_v4(*a, **kw)

    monkeypatch.setattr(parquet_runner_v6, "build_prompt_v4", _spy_v4)
    out_compact = tmp_path / "out_compact.parquet"
    run_docmeta_parquet_sweep(
        _TrackableGemma4Engine(),
        in_pq,
        out_compact,
        chunk_rows=4,
        b_slots=4,
        wire_format="compact",
        use_ane_ring=False,
        escalate_gpt_oss=False,
    )
    assert v4_calls == 0

    # 2. Verify two-phase Pass-2 unloads Gemma-4 BEFORE FastGptOssEngine is instantiated!
    events.clear()
    eng2 = _TrackableGemma4Engine()

    def _flag_row0(objs: Any, _rows: Any) -> list[dict[str, Any]]:
        out = []
        for idx, o in enumerate(objs):
            is_up = "Upgraded" in str(o.get("gist") or "")
            bad = (idx == 0) and not is_up
            out.append({"score": 0.15 if bad else 0.96, "defect_score": 0.85 if bad else 0.04, "is_faithful": not bad, "escalate": bad, "codes": ["atomic_gist_suspect"] if bad else []})
        return out

    summary = run_docmeta_parquet_sweep(
        eng2,
        in_pq,
        out_pq,
        chunk_rows=2,
        b_slots=2,
        wire_format="v4",
        use_ane_ring=False,
        external_verifier=_flag_row0,
        escalate_gpt_oss=True,
        two_phase_pass2=True,
    )
    assert events.index("gemma4_close") < events.index("gpt_oss_init")
    assert eng2.model is None and eng2._w_emb is None and eng2._w_pli14 is None
    assert "gpt_oss_close" in events
    assert summary.pass2_escalated_docs == 2
    assert summary.pass2_accepted_docs == 2
    out_rows = pq.read_table(out_pq).to_pylist()
    assert sum(1 for r in out_rows if r["pass2_escalated"]) == 2
    assert sum(1 for r in out_rows if r["docmeta_source"] == "fast-gpt-oss-20b-pass2") == 2


def test_ane_contention_coordination_and_pure_ane_fallback_guard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_fast_gemma4_grammar(monkeypatch)
    monkeypatch.setenv("DOCMETA_NO_PREFLIGHT_WARN", "1")
    tok = _ByteTokenizer()
    valid_doc = _sample_valid_doc()

    # Pure-ANE helper must refuse silent Metal GPU fallback
    class _BrokenAneEmbedder:
        ane_available = False

    with pytest.raises(RuntimeError, match="ane_available=False"):
        parquet_runner_v6._encode_batch_pure_ane(_BrokenAneEmbedder(), "bge-small", ["hello"])

    class _SilentGpuFallbackEmbedder:
        ane_available = True
        dim = 256
        last_stats = {"ane_docs": 0, "gpu_docs": 1}

        class tokenizer:
            @staticmethod
            def encode_batch(texts: list[str], **_kw: Any) -> list[list[int]]:
                return [[1, 2, 3] for _ in texts]

        def encode_corpus(self, tok_lists: list[list[int]], **kw: Any) -> list[list[float]]:
            assert kw.get("mode") == "ane"
            return [[0.5] * 4 for _ in tok_lists]

    with pytest.raises(RuntimeError, match="silently dispatched 1 doc"):
        parquet_runner_v6._encode_batch_pure_ane(_SilentGpuFallbackEmbedder(), "embeddinggemma-2", ["hello"])

    # When `use_ane_ring=True`, `can_async_stage1` MUST be disabled so Stage-1 doesn't thrash fg4-ane-ring-producer!
    stage1_threads: list[str] = []

    class _FakeEng:
        tokenizer = tok
        new_to_old = list(range(256))
        ane_available = True

        def run_rolling(self, **kwargs: Any) -> dict[str, Any]:
            n = len(kwargs["suf_ids_list"])
            return {
                "gen_toks": [tok.encode(json.dumps(valid_doc, separators=(",", ":"))) for _ in range(n)],
                "prefill_sec": 0.01,
                "decode_sec": 0.01,
                "mask_fallbacks": 0,
                "llm_steps": n,
                "ff_early14_steps": 0,
            }

    class _Stage1Verifier:
        supports_async_ane_stage1 = True

        def run_stage1_ane(self, objs: Any, chunk: Any) -> dict[str, Any]:
            import threading
            stage1_threads.append(threading.current_thread().name)
            return {"objs": objs}

        def finish_stage2(self, s1: dict[str, Any]) -> list[dict[str, Any]]:
            return [{"score": 0.95, "is_faithful": True, "escalate": False} for _ in s1["objs"]]

        def __call__(self, objs: Any, chunk: Any) -> list[dict[str, Any]]:
            return self.finish_stage2(self.run_stage1_ane(objs, chunk))

    in_pq = tmp_path / "ane_in.parquet"
    out_pq = tmp_path / "ane_out.parquet"
    pq.write_table(pa.Table.from_pylist(_sample_queue_rows(4)), in_pq)

    run_docmeta_parquet_sweep(
        _FakeEng(),
        in_pq,
        out_pq,
        chunk_rows=2,
        b_slots=2,
        wire_format="v4",
        use_ane_ring=True,
        external_verifier=_Stage1Verifier(),
    )
    assert stage1_threads and all(t != "docmeta-laya-ane-stage1" for t in stage1_threads)


def test_cli_and_eval_blind_parser_defaults() -> None:
    cli_args = cli.build_parser().parse_args(["docmeta-sweep", "in.parquet", "out.parquet"])
    assert cli_args.kev_batch_docs == 8
    assert cli_args.two_phase_pass2 == "auto"

    eval_args = eval_blind.build_parser().parse_args(["--model-dir", "/tmp/m", "--out", "/tmp/o.json"])
    assert eval_args.b_slots == 256
    assert eval_args.chunk_rows == 4096
    assert eval_args.refill_min == 32
    assert eval_args.kev_batch_docs == 8
    assert eval_args.embed_ane == "none"
    assert eval_args.grammar_router == "none"
    assert eval_args.gpt_oss_model_dir is None
    assert eval_args.gpt_oss_batch_size == 8
    assert eval_args.gpt_oss_k == 1
    assert eval_args.two_phase_pass2 == "auto"


def test_router_fusion_thresholds_and_async_stage1_with_ane_router(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify normalized Top-6 PoE fusion, monotonic router thresholds, fast tau2/tau3, and async Stage-1 with router='ane'."""
    import numpy as np
    import threading
    import warnings
    from congress_docmeta.grammar_router_ane_v6 import fuse_top6_router_probs
    from congress_docmeta.pythonic_v5 import DOC_KINDS_SET

    # 1. Normalized conditional Top-6 PoE preserves tail mass & identity under agreement / alpha=1.0
    rng_probs = np.array([[0.30, 0.25, 0.15, 0.10, 0.08, 0.07, 0.03, 0.02]], dtype=np.float32)
    top6_order = np.array([[0, 1, 2, 3, 4, 5]], dtype=np.int64)
    tail_mass = float(np.sum(rng_probs[0, 6:]))

    fused_alpha1 = fuse_top6_router_probs(rng_probs, top6_order, [0], [[0.90, 0.05, 0.02, 0.01, 0.01, 0.01]], 1.0)
    np.testing.assert_allclose(fused_alpha1[0], rng_probs[0], atol=1e-6)

    p_lin_cond = rng_probs[0, :6] / np.sum(rng_probs[0, :6])
    fused_agree = fuse_top6_router_probs(rng_probs, top6_order, [0], [p_lin_cond.tolist()], 0.35)
    np.testing.assert_allclose(fused_agree[0], rng_probs[0], atol=1e-6)

    fused_blend = fuse_top6_router_probs(rng_probs, top6_order, [0], [[0.02, 0.90, 0.04, 0.02, 0.01, 0.01]], 0.35)
    assert abs(float(np.sum(fused_blend[0])) - 1.0) < 1e-6
    assert abs(float(np.sum(fused_blend[0, 6:])) - tail_mass) < 1e-6
    assert float(fused_blend[0, 1]) > float(fused_blend[0, 0])

    # 2. Monotonic tau_top1 <= tau_top2 <= tau_top3 and separate fast_linear_tau_top2 / top3 + on_truncate='ignore'
    art_dir = tmp_path / "router_art"
    art_dir.mkdir(parents=True)
    dim = 64
    classes = np.array(sorted(DOC_KINDS_SET)[:8])
    W_f16 = np.zeros((len(classes), dim), dtype=np.float16)
    b_f32 = np.zeros((len(classes),), dtype=np.float32)
    b_f32[0] = 0.8
    b_f32[1] = 0.7
    np.savez(art_dir / "router_v63_linear.npz", W_f16=W_f16, b_f32=b_f32, classes=classes, temperature=np.array(1.0), dim=np.array(dim))
    (art_dir / "router_v63_calibration.json").write_text(
        json.dumps(
            {
                "version": "v6_3",
                "fusion_linear_alpha": 0.40,
                "ane_choice_temperature": 1.5,
                "ane_tau_top1": 0.72,
                "ane_tau_top2": 0.88,
                "ane_tau_top3": 0.79,  # Inverted in legacy JSON -> must clamp cleanly >= ane_tau_top2!
                "fast_linear_tau_top1": 0.74,
                "fast_linear_tau_top2": 0.89,
                "fast_linear_tau_top3": 0.94,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCMETA_VALIDATORS_DIR", str(art_dir))

    seen_trunc_modes: list[str] = []

    class _ThreadSafeLayaMock:
        def __init__(self) -> None:
            self._exec_lock = threading.Lock()

        def encode_item(self, st: Any, q: dict[str, Any], *, on_truncate: str = "warn") -> dict[str, Any]:
            seen_trunc_modes.append(on_truncate)
            if on_truncate != "ignore":
                warnings.warn("unexpected truncation", UserWarning)
            return {"q": q}

        def score_choice_batch(self, encs: list[dict[str, Any]], *, temperature_override: float | None = None) -> list[list[float]]:
            assert temperature_override == 1.5
            return [[0.85, 0.08, 0.03, 0.02, 0.01, 0.01][:6] for _ in encs]

        def close(self) -> None:
            pass

    r_fast = PreDecodeGrammarRouterV6(mode="fast", artifacts_dir=art_dir)
    assert (r_fast.tau_top1, r_fast.tau_top2, r_fast.tau_top3) == (0.74, 0.89, 0.94)
    r_fast.close()

    shared_laya = _ThreadSafeLayaMock()
    with warnings.catch_warnings(record=True) as rec_w:
        warnings.simplefilter("always")
        with PreDecodeGrammarRouterV6(mode="ane", artifacts_dir=art_dir, shared_laya_backend=shared_laya) as r_ane:
            assert r_ane.tau_top1 == 0.72
            assert r_ane.tau_top2 == 0.88
            assert r_ane.tau_top3 == 0.88  # Monotonic clamp prevented inverted 0.79 < 0.88!
            decs = r_ane.route_chunk(_sample_queue_rows(2))
            assert len(decs) == 2
    assert seen_trunc_modes and all(m == "ignore" for m in seen_trunc_modes)
    assert not any(issubclass(w.category, UserWarning) for w in rec_w)

    # 3. Async Stage-1 background ANE verification overlaps even with grammar_router='ane' + shared Laya!
    _install_fake_fast_gemma4_grammar(monkeypatch)
    monkeypatch.setenv("DOCMETA_NO_PREFLIGHT_WARN", "1")
    tok = _ByteTokenizer()
    valid_doc = _sample_valid_doc()
    stage1_threads: list[str] = []

    class _FakeEng:
        tokenizer = tok
        new_to_old = list(range(256))
        ane_available = False

        def run_rolling(self, **kwargs: Any) -> dict[str, Any]:
            n = len(kwargs["suf_ids_list"])
            return {
                "gen_toks": [tok.encode(json.dumps(valid_doc, separators=(",", ":"))) for _ in range(n)],
                "prefill_sec": 0.01,
                "decode_sec": 0.01,
                "mask_fallbacks": 0,
                "llm_steps": n,
                "ff_early14_steps": 0,
            }

    class _SharedStage1Verifier:
        supports_async_ane_stage1 = True
        role_repair_min_defect = 0.35

        def __init__(self, laya: Any) -> None:
            self.laya_backend = laya

        def run_stage1_ane(self, objs: Any, chunk: Any) -> dict[str, Any]:
            stage1_threads.append(threading.current_thread().name)
            with self.laya_backend._exec_lock:
                pass
            return {"objs": objs}

        def finish_stage2(self, s1: dict[str, Any]) -> list[dict[str, Any]]:
            return [{"score": 0.95, "defect_score": 0.05, "is_faithful": True, "escalate": False} for _ in s1["objs"]]

        def __call__(self, objs: Any, chunk: Any) -> list[dict[str, Any]]:
            return self.finish_stage2(self.run_stage1_ane(objs, chunk))

    in_pq = tmp_path / "async_in.parquet"
    out_pq = tmp_path / "async_out.parquet"
    pq.write_table(pa.Table.from_pylist(_sample_queue_rows(4)), in_pq)

    run_docmeta_parquet_sweep(
        _FakeEng(),
        in_pq,
        out_pq,
        chunk_rows=2,
        b_slots=2,
        wire_format="v4",
        use_ane_ring=False,
        grammar_router="ane",
        external_verifier=_SharedStage1Verifier(shared_laya),
    )
    assert stage1_threads == ["docmeta-laya-ane-stage1", "docmeta-laya-ane-stage1"]
