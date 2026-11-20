"""Unit & offline sweep tests for CROQ conformal routing, ExtractConf, telemetry, and BM25 opt-in."""

from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import sys
import threading
import types
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_docmeta import (
    CANONICAL_CROQ_KINDS,
    EXTRACTCONF_FEATURE_NAMES_V6,
    ConformalKindRouter,
    LexicalWindowRanker,
    PreDecodeGrammarRouterV6,
    TelemetryPerDocWrapperV6,
    build_croq_union_schema,
    can_wrap_grammar_helper_for_telemetry,
    compute_shared_prefix_ids,
    compute_step_uncertainty,
    infer_current_json_field,
    load_bundled_croq_router_v6,
    load_bundled_extractconf_calibrator_v6,
    pack_bm25_multicrop_text_v6,
    run_docmeta_parquet_sweep,
    split_conformal_quantile,
)


def _write_synthetic_router_artifacts(artifacts_dir: Path, *, include_all_47: bool = True) -> None:
    """Create minimal deterministic linear router NPZ + calibration JSON in ``tmp_path``."""
    import numpy as np

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    base_kinds = list(CANONICAL_CROQ_KINDS if include_all_47 else CANONICAL_CROQ_KINDS[:10])
    classes = base_kinds + ["status:stub_or_blank", "status:garbled_ocr"]
    dim = 4096
    rng = np.random.default_rng(12345)
    W = rng.normal(0.0, 0.002, size=(len(classes), dim)).astype(np.float16)
    b = np.zeros((len(classes),), dtype=np.float32)

    from congress_docmeta.grammar_router_ane_v6 import extract_router_sparse_features_v6

    # Generic buckets shared by unrelated `.pdf` / short / empty-known documents must not trigger cue classes.
    shared_idxs, _ = extract_router_sparse_features_v6("neutral.pdf", "{}", "before the Committee", "before the Committee", dim=dim)
    shared_set = set(shared_idxs)

    # Encode distinct sparse cues onto specific weights so test rows trigger singleton/compact/status cleanly.
    cue_map = {
        "witness_statement": ("wstate_unique_cue.pdf", "Testimony of Jane Doe"),
        "hearing_transcript": ("hearing_unique_cue.pdf", "HEARING APPROPRIATIONS TRANSCRIPT"),
        "oversight_letter": ("letter_unique_cue.pdf", "Dear Chairman oversight letter"),
        "status:stub_or_blank": ("blank_unique_cue.pdf", ""),
    }
    for cls_name, (fn, txt) in cue_map.items():
        if cls_name not in classes:
            continue
        ci = classes.index(cls_name)
        idxs, vals = extract_router_sparse_features_v6(fn, "{}", txt, txt, dim=dim)
        for ix, v in zip(idxs, vals):
            if ix in shared_set:
                continue
            W[ci, ix] = np.float16(180.0 * v)
    # Suppress background false positives on status:* classes unless the strong blank/garbled cue fires.
    for st_cls in ("status:stub_or_blank", "status:garbled_ocr"):
        if st_cls in classes:
            b[classes.index(st_cls)] = -15.0

    np.savez(
        artifacts_dir / "router_v63_linear.npz",
        W_f16=W,
        b_f32=b,
        classes=np.asarray(classes),
        dim=np.asarray(dim, dtype=np.int32),
        temperature=np.asarray(1.0, dtype=np.float32),
    )
    (artifacts_dir / "router_v63_calibration.json").write_text(
        json.dumps(
            {
                "fusion_linear_alpha": 0.45,
                "ane_choice_temperature": 1.0,
                "fast_linear_tau_top1": 0.90,
                "fast_linear_tau_top2": 0.90,
                "fast_linear_tau_top3": 0.93,
            }
        ),
        encoding="utf-8",
    )


def test_stdlib_isolation_and_all_exports_clean() -> None:
    """Top-level package imports must pass under ``/usr/bin/python3 -B -I -S`` with all exports present."""
    src_root = Path(__file__).resolve().parents[1] / "src"
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(src_root)!r});"
        "import congress_docmeta;"
        "from congress_docmeta import grammar_router_ane_v6, telemetry_v6, extractconf_v6, lexical_multicrop_v6, parquet_runner_v6;"
        "missing = [k for k in congress_docmeta.__all__ if not hasattr(congress_docmeta, k)];"
        "assert not missing, f'Missing exports: {missing}';"
        "cal = extractconf_v6.load_bundled_extractconf_calibrator_v6();"
        "croq = grammar_router_ane_v6.load_bundled_croq_router_v6();"
        "assert len(cal.feature_names) == 73 and croq.q_hat > 0;"
    )
    proc = subprocess.run(
        ["/usr/bin/python3", "-B", "-I", "-S", "-c", code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}\nstdout={proc.stdout}"


def test_split_conformal_quantile_and_croq_coverage_and_union_schema() -> None:
    assert len(CANONICAL_CROQ_KINDS) == 47
    # Small-sample boundary: ceil((10 + 1) * 0.95) = 11 > 10 -> +inf guarantees coverage
    assert split_conformal_quantile([0.1 * i for i in range(10)], alpha=0.05) == float("inf")
    q95 = split_conformal_quantile([i / 100.0 for i in range(100)], alpha=0.05)
    assert math.isclose(q95, 0.95, abs_tol=1e-9)

    router = load_bundled_croq_router_v6()
    assert isinstance(router, ConformalKindRouter)
    assert math.isclose(router.alpha, 0.05, abs_tol=1e-9)
    assert router.score_mode == "aps_det"
    assert router.max_lock_k == 4
    assert router.n_cal == 410
    assert router.cal_summary["empirical_coverage"] >= 0.95

    with pytest.raises(ValueError, match="calibrated at alpha=0.05"):
        load_bundled_croq_router_v6(alpha=0.10)

    # Synthetic 47-dim distributions testing singleton, compact set (<=4), and open fallback (>4)
    k = len(router.kinds)
    p_single = [0.0] * k
    p_single[0] = 0.96
    for i in range(1, k):
        p_single[i] = 0.04 / (k - 1)
    d_single = router.route_one(p_single)
    assert d_single.lock_type == "croq_singleton"
    assert d_single.set_size == 1
    assert d_single.lock_spec == router.kinds[0]

    p_pair = [0.0] * k
    p_pair[0] = 0.55
    p_pair[1] = 0.43
    for i in range(2, k):
        p_pair[i] = 0.02 / (k - 2)
    d_pair = router.route_one(p_pair)
    assert d_pair.lock_type == "croq_compact_set"
    assert 2 <= d_pair.set_size <= 4
    assert set(d_pair.lock_spec.split("|")) == set(d_pair.conformal_set)  # type: ignore[union-attr]

    p_flat = [1.0 / k] * k
    d_open = router.route_one(p_flat)
    assert d_open.lock_type == "croq_open"
    assert d_open.set_size > 4
    assert d_open.lock_spec is None

    # Both compact & V4 union schemas narrow primary_kind enum strictly
    compact_union = build_croq_union_schema([router.kinds[0], router.kinds[1]], wire_format="compact")
    assert set(compact_union["properties"]["pk"]["enum"]) == {router.kinds[0], router.kinds[1]}
    v4_union = build_croq_union_schema([router.kinds[0], router.kinds[1]], wire_format="v4")
    assert set(v4_union["properties"]["primary_kind"]["enum"]) == {router.kinds[0], router.kinds[1]}


def test_predecode_router_fast_croq_routing_and_fallbacks(tmp_path: Path) -> None:
    full_art = tmp_path / "art_full"
    _write_synthetic_router_artifacts(full_art, include_all_47=True)

    with PreDecodeGrammarRouterV6(mode="fast", artifacts_dir=full_art) as router:
        assert router.croq_router is not None
        rows = [
            {"filename": "wstate_unique_cue.pdf", "p12_clean_text": "Testimony of Jane Doe before the Committee"},
            {"filename": "ambig.pdf", "p12_clean_text": "short neutral note with no strong cues"},
            {"filename": "blank_unique_cue.pdf", "p12_clean_text": ""},
        ]
        pmetas = [{"known_str": "{}"}, {"known_str": "{}"}, {"known_str": "{}"}]
        decs = router.route_chunk(rows, pmetas)
        assert decs[0]["lock_type"] == "croq_singleton"
        assert decs[0]["lock_spec"] == "witness_statement"
        assert decs[0]["conformal_set"] == ["witness_statement"]
        assert decs[1]["lock_type"] == "croq_open"
        assert decs[1]["lock_spec"] is None
        assert decs[2]["lock_type"] == "croq_open_status"
        assert decs[2]["lock_spec"] is None

    # Explicit tau_top* bypasses CROQ cleanly
    with PreDecodeGrammarRouterV6(mode="fast", artifacts_dir=full_art, tau_top1=0.80) as router_legacy:
        assert router_legacy.croq_router is None
        dec_l = router_legacy.route_chunk(
            [{"filename": "wstate_unique_cue.pdf", "p12_clean_text": "Testimony of Jane Doe before the Committee"}],
            [{"known_str": "{}"}],
        )[0]
        assert dec_l["lock_type"] == "fast_top1"

    # Mock routers with <47 classes auto-fallback safely without error under use_croq='auto'
    sub_art = tmp_path / "art_sub"
    _write_synthetic_router_artifacts(sub_art, include_all_47=False)
    with PreDecodeGrammarRouterV6(mode="fast", artifacts_dir=sub_art, use_croq="auto") as router_sub:
        assert router_sub.croq_router is None


def test_compute_shared_prefix_ids_prevents_empty_known_bpe_over_clamp() -> None:
    """Reproduces `' {"'` BPE merge across ``known='{"a": 1}'`` vs ``known='{}'``."""
    MARKER = ': {"'
    EMPTY_KNOWN = ": {}"

    class _BpeMergeTok:
        def encode(self, text: str) -> list[int]:
            # Emit distinct merged token ID for `": {\""` vs `": {}"` at the `known_metadata` boundary
            out: list[int] = []
            i = 0
            while i < len(text):
                if text.startswith(MARKER, i):
                    out.append(9001)
                    i += len(MARKER)
                elif text.startswith(EMPTY_KNOWN, i):
                    out.append(9002)
                    i += len(EMPTY_KNOWN)
                else:
                    out.append(ord(text[i]))
                    i += 1
            return out

    tok = _BpeMergeTok()

    def _fmt(k_s: str, fn: str, txt: str) -> str:
        return f"SYS|known: {k_s}|file:{fn}|body:{txt}"

    shared = compute_shared_prefix_ids(tok.encode, _fmt)
    empty_ids = tok.encode(_fmt("{}", "doc.pdf", "Hello"))
    nonempty_ids = tok.encode(_fmt('{"chamber": "house"}', "doc.pdf", "Hello"))
    none_ids = tok.encode(_fmt("none", "doc.pdf", "Hello"))
    # Naive 2-probe LCP over {"a":1} vs {"b":2} would wrongly include 9001 and diverge on empty_ids!
    assert 9001 not in shared
    assert empty_ids[: len(shared)] == shared
    assert nonempty_ids[: len(shared)] == shared
    assert none_ids[: len(shared)] == shared


def test_telemetry_field_attribution_uncertainty_and_wrapper() -> None:
    # Field attribution handles compact short keys AND V4 keys + escaped strings/brackets
    assert infer_current_json_field('{"st":"usable","vt":"Title with {braces}","cm":[') == "committees"
    assert infer_current_json_field('{"st":"usable","pk":"wit') == "primary_kind"
    assert infer_current_json_field('{"status":"usable","personas":[{"name":"Al') == "personas"

    h_unif, nlz_u, z_u = compute_step_uncertainty([0.0, 0.0, 0.0, 0.0], [True, True, True, True])
    assert math.isclose(h_unif, math.log(4.0), rel_tol=1e-6)
    assert math.isclose(nlz_u, 0.0, abs_tol=1e-9)
    assert math.isclose(z_u, 1.0, abs_tol=1e-9)

    # logits strongly prefer invalid token 0 -> small z_valid, high neg_log_z
    h_skew, nlz_s, z_s = compute_step_uncertainty([10.0, 0.0], [False, True])
    assert h_skew > 0.0
    assert z_s < 1e-4
    assert nlz_s > 9.0

    # Mock GrammarHelper exposing llguidance-style mask buffers + greedy enforcement
    class _FakeLTok:
        vocab_size = 8

        def decode_bytes(self, tids: list[int]) -> bytes:
            tokens = {
                0: b"{",
                1: b'"pk":',
                2: b'"bill"',
                3: b',"dd":',
                4: b'"2024"',
                5: b"}",
                6: b"x",
                7: b"y",
            }
            return b"".join(tokens.get(t, b"?") for t in tids)

    class _FakeMatcher:
        def __init__(self) -> None:
            self.tokens: list[int] = []

        def unsafe_compute_mask_ptr(self, _ptr: int, _nbytes: int) -> None:
            pass

        def compute_ff_tokens(self) -> list[int]:
            return [3] if self.tokens == [0, 1, 2] else []

        def try_consume_tokens(self, toks: list[int]) -> int:
            self.tokens.extend(toks)
            return len(toks)

        def consume_tokens(self, toks: list[int]) -> bool:
            self.tokens.extend(toks)
            return True

        def consume_token(self, tok_id: int) -> bool:
            self.tokens.append(tok_id)
            return True

        def validate_tokens(self, _toks: list[int]) -> bool:
            return True

        def is_stopped(self) -> bool:
            return False

        def is_accepting(self) -> bool:
            return True

    import numpy as np

    class _FakeMaskHelper:
        def __init__(self) -> None:
            self.ltok = _FakeLTok()
            self.tok = object()
            self.upfront_ff = [0, 1]
            self.new_to_old = np.arange(8, dtype=np.int32)
            self._mask_lock = threading.Lock()
            self._mask_ptr = 0
            self._mask_nbytes = 4
            self._mask_buf = np.array([0xFFFFFFFF], dtype=np.uint32)
            self.k_word = np.zeros((8,), dtype=np.int32)
            self.k_bit = np.arange(8, dtype=np.int32)
            self.seen_temps: list[float] = []

        def new_matcher(self) -> _FakeMatcher:
            return _FakeMatcher()

        def pick_valid_token(
            self,
            _m: Any,
            logits_1d: Any,
            _argmax: int,
            *,
            temperature: float = 0.0,
            **_: Any,
        ) -> tuple[int, bool]:
            self.seen_temps.append(temperature)
            return int(np.argmax(logits_1d)), False

        def validate_token_sequence(self, _ids: Any) -> bool:
            return True

    assert can_wrap_grammar_helper_for_telemetry(object()) is False
    base = _FakeMaskHelper()
    assert can_wrap_grammar_helper_for_telemetry(base) is True

    wrapped = TelemetryPerDocWrapperV6(base, force_greedy=True)
    m = wrapped.new_matcher_for_doc(0)
    assert m.current_field() == "primary_kind"
    logits = np.zeros((8,), dtype=np.float32)
    logits[2] = 5.0
    tok_picked, _ = wrapped.pick_valid_token(m, logits, 2, temperature=1e-4)
    assert tok_picked == 2
    assert base.seen_temps == [0.0]  # force_greedy=True overrides 1e-4 -> 0.0
    m.consume_tokens([2, 3])
    assert m.current_field() == "doc_date"
    logits2 = np.zeros((8,), dtype=np.float32)
    logits2[4] = 4.0
    wrapped.pick_valid_token(m, logits2, 4, temperature=1e-4)

    summ = wrapped.summarize_doc(0)
    assert summ.steps == 2
    assert "primary_kind" in summ.by_field
    assert "doc_date" in summ.by_field
    flat = summ.to_flat_features()
    assert flat["tel_steps"] == 2.0
    assert flat["tel_primary_kind_max_h"] > 0.0


def test_extractconf_bundled_calibrator_and_lexical_ranker() -> None:
    cal = load_bundled_extractconf_calibrator_v6()
    assert len(cal.feature_names) == 73
    assert EXTRACTCONF_FEATURE_NAMES_V6[0] == "v0_risk_unit"

    clean_rec = {
        "filename": "wstate_smith.pdf",
        "text_len": 1200,
        "locked_primary_kind": "witness_statement",
        "pass1_pred": {
            "primary_kind": "witness_statement",
            "doc_date": "2024-03-15",
            "date_spans": ["2024-03-15"],
            "committees": ["Committee on Energy and Commerce"],
            "personas": [{"name": "Jane Smith", "role": "witness", "org": "ACME"}],
        },
        "v0_raw": {"atomic_risk_score": 0.0, "gist_miss_frac": 0.0},
    }
    risky_rec = {
        "filename": "wstate_20240315_smith.pdf",
        "text_len": 4800,
        "locked_primary_kind": None,
        "router_fast": {"top1_class": "hearing_transcript", "top1_prob": 0.41, "lock_type": "croq_open", "top_candidates": [("hearing_transcript", 0.41), ("witness_statement", 0.39)]},
        "pass1_pred": {
            "primary_kind": "oversight_letter",  # contradicts wstate_ slug
            "doc_date": None,
            "date_spans": [],
            "committees": [],
            "personas": [],
        },
        "v0_raw": {
            "atomic_risk_score": 1.4,
            "kind_conflicts": ["slug_wstate"],
            "ungrounded_committees": [],
            "ungrounded_dates": ["2024-01-01"],
            "persona_omission_flags": ["witness_omitted"],
            "gist_miss_frac": 0.85,
        },
        "telemetry": {
            "tel_steps": 180.0,
            "tel_mean_h_pre": 1.2,
            "tel_max_h_pre": 3.4,
            "tel_mean_neg_log_z": 0.4,
            "tel_max_neg_log_z": 2.9,
            "tel_min_z_valid": 0.055,
            "tel_primary_kind_max_h": 2.8,
            "tel_primary_kind_max_nlz": 2.5,
            "tel_dates_max_h": 1.5,
        },
    }
    out_clean = cal.score_record(clean_rec)
    out_risky = cal.score_record(risky_rec)
    assert out_clean["source_regime"] == "fast_no_tel"
    assert out_risky["source_regime"] == "fast+tel"
    assert out_risky["any_defect_prob"] > out_clean["any_defect_prob"]
    assert out_risky["field_probs"]["primary_kind"] > out_clean["field_probs"]["primary_kind"]
    assert out_risky["escalate_recommended"] is True
    assert len(out_risky["flagged_fields"]) <= 2

    # LexicalWindowRanker & opt-in BM25 multicrop packing
    short = "Short testimony of Dr. Alice Jones."
    packed_s, spans_s = pack_bm25_multicrop_text_v6(short, long_threshold=3000)
    assert packed_s == short and spans_s == []

    filler = ("Standard procedural boilerplate paragraph with minimal relevant entities.\n" * 60)
    middle_cue = "STATEMENT OF SENATOR JANE DOE, CHAIRWOMAN, COMMITTEE ON APPROPRIATIONS, MARCH 12, 2024."
    long_txt = ("Header opening text.\n" * 30) + filler + middle_cue + "\n" + filler + "\nClosing signature."
    assert len(long_txt) > 3000
    packed_l, spans_l = pack_bm25_multicrop_text_v6(
        long_txt,
        conformal_set=["hearing_transcript", "witness_statement"],
        long_threshold=3000,
        top_k=2,
    )
    assert len(packed_l) < len(long_txt)
    assert spans_l and "APPROPRIATIONS" in packed_l
    ranker_tf = LexicalWindowRanker(method="tfidf")
    scores_tf = ranker_tf.score_windows([filler[:300], middle_cue], ["committee appropriations march"])
    assert scores_tf[1] > scores_tf[0]


def test_offline_sweep_defaults_croq_telemetry_extractconf_and_optin_bm25(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline sweep verifies new production defaults: fast CROQ + Telemetry + ExtractConf, uncut text, no heavy stages."""
    import numpy as np
    from congress_docmeta import eval_blind as _eval_blind  # noqa: F401
    from congress_docmeta import parquet_runner_v6

    router_art = tmp_path / "router_arts"
    _write_synthetic_router_artifacts(router_art, include_all_47=True)

    # Real BPE-like tokenizer simulating `': {"'` vs `': {}'` token merge + mask-buffer GrammarHelper
    MARKER = ': {"'
    EMPTY_KNOWN = ": {}"

    class _MockTok:
        def apply_chat_template(self, msgs: list[dict[str, str]], **_: Any) -> str:
            return msgs[0]["content"]

        def encode(self, text: str, **_: Any) -> list[int]:
            out: list[int] = []
            i = 0
            while i < len(text):
                if text.startswith(MARKER, i):
                    out.append(254)
                    i += len(MARKER)
                elif text.startswith(EMPTY_KNOWN, i):
                    out.append(255)
                    i += len(EMPTY_KNOWN)
                else:
                    b = text[i].encode("utf-8")
                    out.extend(list(b))
                    i += 1
            return out

        def decode(self, ids: list[int], **_: Any) -> str:
            parts: list[bytes] = []
            for tid in ids:
                if tid == 254:
                    parts.append(MARKER.encode("utf-8"))
                elif tid == 255:
                    parts.append(EMPTY_KNOWN.encode("utf-8"))
                else:
                    parts.append(bytes([tid % 256]))
            return b"".join(parts).decode("utf-8", errors="replace")

    tok = _MockTok()

    class _MockLTok:
        vocab_size = 256

        def decode_bytes(self, tids: list[int]) -> bytes:
            return tok.decode(list(tids)).encode("utf-8")

    class _MockMatcher:
        def __init__(self) -> None:
            self.consumed: list[int] = []

        def unsafe_compute_mask_ptr(self, _ptr: int, _nbytes: int) -> None:
            pass

        def compute_ff_tokens(self) -> list[int]:
            return []

        def try_consume_tokens(self, toks: list[int]) -> int:
            self.consumed.extend(toks)
            return len(toks)

        def consume_tokens(self, toks: list[int]) -> bool:
            self.consumed.extend(toks)
            return True

        def consume_token(self, tok_id: int) -> bool:
            self.consumed.append(tok_id)
            return True

        def validate_tokens(self, _toks: list[int]) -> bool:
            return True

        def is_stopped(self) -> bool:
            return False

        def is_accepting(self) -> bool:
            return True

    class _MockGH:
        def __init__(self, t: Any, schema: Any, new_to_old: Any = None, **_: Any) -> None:
            self.tok = t
            self.tokenizer = t
            self.ltok = _MockLTok()
            self.upfront_ff = [ord("{")]
            self.new_to_old = new_to_old if new_to_old is not None else np.arange(256, dtype=np.int32)
            self._mask_lock = threading.Lock()
            self._mask_ptr = 0
            self._mask_nbytes = 32
            self._mask_buf = np.full((8,), 0xFFFFFFFF, dtype=np.uint32)
            self.k_word = np.zeros((256,), dtype=np.int32)
            self.k_bit = np.arange(256, dtype=np.int32) % 32

        def new_matcher(self) -> _MockMatcher:
            return _MockMatcher()

        def pick_valid_token(self, _m: Any, logits_1d: Any, _arg: int, **_: Any) -> tuple[int, bool]:
            return int(np.argmax(logits_1d)), False

        def validate_token_sequence(self, _ids: Any) -> bool:
            return True

    class _MockPerDocGH:
        def __init__(self, gh_std: Any, doc_order: Any = (), **kwargs: Any) -> None:
            self._gh_std = gh_std
            self.tok = gh_std.tok
            self.ltok = gh_std.ltok
            self.upfront_ff = list(gh_std.upfront_ff)
            self.new_to_old = gh_std.new_to_old
            self._doc_schema_keys = dict(kwargs.get("doc_schema_keys") or {})
            self._cursor = 0
            self.dispatched_doc_indices: list[int] = []
            self._cache = kwargs.get("grammar_cache") if kwargs.get("grammar_cache") is not None else {}

        def get_grammar_entry(self, key: str) -> tuple[str, list[int]]:
            entry = self._cache.get(key)
            if entry is None:
                entry = (key, [])
                self._cache[key] = entry
            return entry

        def upfront_ff_for_doc(self, _doc_idx: int) -> list[int]:
            return list(self.upfront_ff)

        def new_matcher_for_doc(self, doc_idx: int) -> _MockMatcher:
            self._cursor += 1
            self.dispatched_doc_indices.append(int(doc_idx))
            return _MockMatcher()

        def new_matcher(self) -> _MockMatcher:
            self._cursor += 1
            return _MockMatcher()

        def pick_valid_token(self, m: Any, logits_1d: Any, arg: int, *a: Any, **kw: Any) -> tuple[int, bool]:
            return self._gh_std.pick_valid_token(m, logits_1d, arg, *a, **kw)

        def validate_token_sequence(self, full_ids: Any) -> bool:
            return True

    fg4_pkg = types.ModuleType("fast_gemma4")
    fg4_gram = types.ModuleType("fast_gemma4.grammar")
    fg4_gram.GrammarHelper = _MockGH  # type: ignore[attr-defined]
    fg4_pdg = types.ModuleType("fast_gemma4.per_doc_grammar")
    fg4_pdg.PerDocGrammarHelper = _MockPerDocGH  # type: ignore[attr-defined]
    fg4_pdg.compute_rolling_doc_order = lambda suf_ids, **_: list(range(len(suf_ids)))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fast_gemma4", fg4_pkg)
    monkeypatch.setitem(sys.modules, "fast_gemma4.grammar", fg4_gram)
    monkeypatch.setitem(sys.modules, "fast_gemma4.per_doc_grammar", fg4_pdg)

    def _forbidden(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("Default sweep must not initialize GPT-OSS or heavy neural validators")

    import congress_docmeta.atomic_validator_v6 as av6

    monkeypatch.setattr(av6, "AtomicOutputValidatorV6", _forbidden)
    monkeypatch.setattr(parquet_runner_v6, "escalate_anomalies_gpt_oss", _forbidden)

    valid_v4 = {
        "status": "usable",
        "text_quality": "native",
        "chamber": "house",
        "congress": 118,
        "committees": ["Committee on Appropriations"],
        "doc_date": "2024-03-15",
        "date_spans": ["2024-03-15"],
        "primary_kind": "witness_statement",
        "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
        "composed_title": "Testimony of Jane Doe Before Appropriations",
        "gist": "Jane Doe testifies before the House Appropriations Committee on FY2025 funding.",
        "topics": ["appropriations"],
    }
    full_enc = tok.encode(json.dumps(valid_v4, separators=(",", ":")))
    gen_suffix = full_enc[1:]  # upfront_ff has '{'

    class _FakeSweepEngine:
        def __init__(self) -> None:
            self.tokenizer = tok
            self.new_to_old = np.arange(256, dtype=np.int32)
            self.calls: list[dict[str, Any]] = []
            self.decoded_prompts: list[str] = []

        def run_rolling(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            gh = kwargs["gh"]
            sys_ids = kwargs["sys_ids"]
            for di, suf in enumerate(kwargs["suf_ids_list"]):
                self.decoded_prompts.append(tok.decode(sys_ids + suf))
                m = gh.new_matcher_for_doc(di)
                logits = np.zeros((256,), dtype=np.float32)
                step_tok = gen_suffix[min(1, len(gen_suffix) - 1)]
                logits[step_tok] = 4.0
                gh.pick_valid_token(m, logits, step_tok, temperature=float(kwargs.get("temperature", 0.0)))
            n = len(kwargs["suf_ids_list"])
            return {
                "gen_toks": [list(gen_suffix) for _ in range(n)],
                "prefill_sec": 0.01,
                "decode_sec": 0.02,
                "mask_fallbacks": 0,
                "llm_steps": n,
                "ff_early14_steps": 0,
            }

    filler = ("General background statement boilerplate sentence for testing.\n" * 65)
    long_text = "Testimony of Jane Doe before the Committee on Appropriations March 15, 2024.\n" + filler + "\nClosing."
    assert len(long_text) > 3500
    rows_in = [
        {
            "link_key_hex": "0000000000000001",
            "list_row": 0,
            "filename": "wstate_unique_cue.pdf",
            "known_json": "{}",
            "p12_clean_text": long_text,
            "p12_raw_text": long_text,
        },
        {
            "link_key_hex": "0000000000000002",
            "list_row": 1,
            "filename": "ambig.pdf",
            "known_json": json.dumps({"chamber": "house"}),
            "p12_clean_text": "Neutral procedural text without strong cues.",
            "p12_raw_text": "Neutral procedural text without strong cues.",
        },
    ]
    in_pq = tmp_path / "in.parquet"
    pq.write_table(pa.Table.from_pylist(rows_in), in_pq)

    # 1. Default settings: CROQ fast, full uncut text, telemetry auto -> active, ExtractConf enabled, no GPT-OSS
    out_def = tmp_path / "out_default.parquet"
    eng_def = _FakeSweepEngine()
    sum_def = run_docmeta_parquet_sweep(
        eng_def,
        in_pq,
        out_def,
        wire_format="v4",
        use_ane_ring=False,
        router_artifacts_dir=router_art,
    )
    assert sum_def.docs_processed == 2
    assert sum_def.pass2_escalated_docs == 0
    assert sum_def.telemetry_wrapped_chunks == 1
    assert eng_def.calls[0].get("temperature") == 1e-4
    # Full uncut text reaches the LLM prompt by default (`bm25_multicrop=False`)!
    assert "Closing." in eng_def.decoded_prompts[0] and "[EVIDENCE @" not in eng_def.decoded_prompts[0]
    # First row matches singletons (`wstate_unique_cue.pdf`), second falls back to `croq_open` (`None`)
    res_rows = sorted(pq.read_table(out_def).to_pylist(), key=lambda r: r["list_row"])
    assert res_rows[0]["croq_lock_spec"] == "witness_statement"
    assert res_rows[0]["croq_lock_type"] == "croq_singleton"
    assert res_rows[1]["croq_lock_spec"] is None
    assert res_rows[1]["croq_lock_type"] == "croq_open"
    ec0 = json.loads(res_rows[0]["extractconf_risk_json"])
    assert ec0["has_telemetry"] is True and ec0["source_regime"] == "fast+tel"
    assert set(ec0["field_probs"]) == {"personas", "committees", "dates", "primary_kind"}

    # 2. Opt-in `bm25_multicrop=True` crops long prompt + `use_telemetry="off"` skips temperature=1e-4 & keeps ExtractConf
    out_bm25 = tmp_path / "out_bm25.parquet"
    eng_bm25 = _FakeSweepEngine()
    sum_bm25 = run_docmeta_parquet_sweep(
        eng_bm25,
        in_pq,
        out_bm25,
        wire_format="v4",
        use_ane_ring=False,
        router_artifacts_dir=router_art,
        bm25_multicrop=True,
        use_telemetry="off",
    )
    assert sum_bm25.telemetry_wrapped_chunks == 0
    assert "temperature" not in eng_bm25.calls[0]
    assert "[EVIDENCE @" in eng_bm25.decoded_prompts[0]
    res_bm25 = sorted(pq.read_table(out_bm25).to_pylist(), key=lambda r: r["list_row"])
    ec_no_tel = json.loads(res_bm25[0]["extractconf_risk_json"])
    assert ec_no_tel["has_telemetry"] is False and ec_no_tel["source_regime"] == "fast_no_tel"
