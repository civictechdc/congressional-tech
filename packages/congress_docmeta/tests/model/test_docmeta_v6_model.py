"""DocMeta against the fast-gemma4 engine seam: per-document grammars, `PythonicEngineV6` and the sweep.

Run by the `docmeta-model` lane (the fast-gemma4 interpreter with this checkout's `congress_docmeta` on the path).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fast_gemma4", reason="needs the fast-gemma4 engine; run scripts/dev.py test docmeta-model")

from congress_docmeta import (  # noqa: E402
    SCHEMA_V4_STR,
    PerDocGrammarHelperV6,
    SyncKindMatcher,
    compute_rolling_doc_order,
    post_pass_v6,
    strict_validate_v4,
)
from fast_gemma4.grammar import GrammarHelper  # noqa: E402
from fast_gemma4.paths import resolve_paths  # noqa: E402
from fast_gemma4.tokenizer import FastGemma4Tokenizer, VocabRemapper  # noqa: E402


def test_sync_kind_matcher_and_per_doc_grammar_helper_v6() -> None:
    """Verify `PerDocGrammarHelperV6` and `SyncKindMatcher` align upfront FF tokens and lock per-slot `primary_kind`."""
    paths = resolve_paths()
    tok_json = paths.resolve_tokenizer_json()
    tok = FastGemma4Tokenizer(tok_json)
    rem = VocabRemapper.load_or_build(tok_json, paths.vocab_remap_npz)
    gh_std = GrammarHelper(tok, SCHEMA_V4_STR, rem.kept_old_ids, whitespace_flexible=False)

    helper = PerDocGrammarHelperV6(
        gh_std,
        doc_order=[0, 1],
        doc_target_kinds={0: "truth_in_testimony_disclosure"},
        sync_ff_with_std=True,
    )
    assert helper.upfront_ff_for_doc(0) == list(gh_std.upfront_ff)
    assert helper.upfront_ff_for_doc(1) == list(gh_std.upfront_ff)

    m_locked = helper.new_matcher()
    m_open = helper.new_matcher()
    assert isinstance(m_locked, SyncKindMatcher)

    valid_ttf_json = json.dumps(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "truth_in_testimony_disclosure",
            "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
            "disclosure": {"capacity": "organization", "gov_witness": False},
            "composed_title": "Truth in Testimony Disclosure of Jane Doe",
            "gist": "Disclosure form filed by witness Jane Doe.",
            "topics": ["oversight"],
        },
        separators=(",", ":"),
    )
    wrong_kind_json = valid_ttf_json.replace("truth_in_testimony_disclosure", "hearing_transcript")

    ttf_ids = tok.encode(valid_ttf_json, add_special_tokens=False)
    wrong_ids = tok.encode(wrong_kind_json, add_special_tokens=False)
    up_len = len(gh_std.upfront_ff)
    assert ttf_ids[:up_len] == list(gh_std.upfront_ff)

    # Locked matcher accepts `truth_in_testimony_disclosure` suffix and rejects `hearing_transcript`
    assert m_locked.try_consume_tokens(ttf_ids[up_len:]) == len(ttf_ids[up_len:])
    assert m_locked.is_accepting()

    helper_retry = PerDocGrammarHelperV6(
        gh_std,
        doc_order=[0],
        doc_target_kinds={0: "truth_in_testimony_disclosure"},
        sync_ff_with_std=True,
    )
    m_locked_reject = helper_retry.new_matcher()
    n_bad = m_locked_reject.try_consume_tokens(wrong_ids[up_len:])
    assert n_bad < len(wrong_ids[up_len:])

    # Unlocked slot accepts `hearing_transcript`
    assert m_open.try_consume_tokens(wrong_ids[up_len:]) == len(wrong_ids[up_len:])
    # SyncKindMatcher exposes validate_tokens for GrammarHelper fallback compatibility
    assert m_locked_reject.validate_tokens(wrong_ids[up_len + n_bad : up_len + n_bad + 1]) is False
    assert m_locked_reject.validate_tokens(ttf_ids[up_len + n_bad : up_len + n_bad + 1]) is True




def test_pythonic_engine_v6_fast_gemma4_engine_seam_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify `PythonicEngineV6` runs natively on `FastGemma4Engine` (`apply_chat_template` + `run_rolling` + `SyncKindMatcher`)."""
    import numpy as np

    import fast_gemma4.speculative as fg4_spec
    from congress_docmeta import PythonicEngineV6
    from fast_gemma4.engine import FastGemma4Engine

    paths = resolve_paths()
    tok = FastGemma4Tokenizer(paths.resolve_tokenizer_json())
    rem = VocabRemapper.load_or_build(paths.resolve_tokenizer_json(), paths.vocab_remap_npz)

    class _FakeArray:
        def __init__(self, data) -> None:
            self.data = np.asarray(data)

        @property
        def shape(self):
            return self.data.shape

        def tolist(self):
            return self.data.tolist()

        def astype(self, _dt):
            return self

        def __getitem__(self, key):
            return _FakeArray(self.data[key.data if isinstance(key, _FakeArray) else key])

        def __array__(self, dtype=None):
            return np.asarray(self.data, dtype=dtype)

    class _FakeMx:
        int32 = "int32"
        float32 = "float32"

        def array(self, d, dtype=None):
            return _FakeArray(np.array(d, dtype=np.int32 if dtype == "int32" else np.float32))

        def eval(self, *args):
            pass

    fake_mx = _FakeMx()
    valid_ttf = json.dumps(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "truth_in_testimony_disclosure",
            "personas": [{"name": "Marcus Holloway", "role": "witness", "entity_type": "non_gov_person"}],
            "disclosure": {"capacity": "organization", "gov_witness": False},
            "composed_title": "Truth in Testimony Disclosure",
            "gist": "Witness disclosure.",
            "topics": ["oversight"],
        },
        separators=(",", ":"),
    )
    valid_open = json.dumps(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "hearing_transcript",
            "composed_title": "House Oversight Hearing",
            "gist": "Committee hearing transcript.",
            "topics": ["oversight"],
        },
        separators=(",", ":"),
    )
    tok_ttf_full = tok.encode(valid_ttf, add_special_tokens=False) + [tok.eos_token_id]
    tok_open_full = tok.encode(valid_open, add_special_tokens=False) + [tok.eos_token_id]

    gh_std_ref = GrammarHelper(tok, SCHEMA_V4_STR, rem.kept_old_ids, whitespace_flexible=False)
    helper_ref = PerDocGrammarHelperV6(
        gh_std_ref, [0, 1], doc_target_kinds={0: "truth_in_testimony_disclosure"}, sync_ff_with_std=True
    )

    def _non_ff_steps(matcher: Any, full_ids: list[int], up_len: int) -> list[int]:
        pos = up_len
        out: list[int] = []
        while pos < len(full_ids):
            tid = full_ids[pos]
            assert matcher.consume_token(tid), f"Matcher rejected token {tid} at pos={pos}"
            out.append(tid)
            pos += 1
            if matcher.is_stopped():
                break
            ff = matcher.compute_ff_tokens()
            if ff:
                matcher.consume_tokens(ff)
                pos += len(ff)
                if matcher.is_stopped():
                    break
        return out

    up_len = len(gh_std_ref.upfront_ff)
    tok_ttf = _non_ff_steps(helper_ref.new_matcher_for_doc(0), tok_ttf_full, up_len)
    tok_open = _non_ff_steps(helper_ref.new_matcher_for_doc(1), tok_open_full, up_len)

    class _MockModel:
        window_size = 512
        kv_i8 = True
        new_to_old = rem.kept_old_ids

        def __init__(self, scripts: dict[int, list[int]]) -> None:
            self.scripts = scripts
            self.slot_doc: dict[int, int] = {}
            self.cursor: dict[int, int] = {}

        def make_slot_cache(self, prefix_kv, batch_size, doc_cap_full=1440, swa_ring_cap=512, kv_i8=None):
            return {"batch_size": batch_size, "l_sys": prefix_kv["l_sys"], "swa_cap": swa_ring_cap, "layers": []}

        def prefill_slots_lazy_lg(self, sub_sufs, target_slots, cache, *, group_size=16, return_logits=False, async_eval=False):
            min_len = min(len(x) for x in sub_sufs)
            am = []
            offs = []
            for r, s in enumerate(target_slots):
                doc_id = 0 if len(sub_sufs[r]) == min_len else 1
                self.slot_doc[s] = doc_id
                self.cursor[doc_id] = 0
                t = self.scripts[doc_id][self.cursor[doc_id]]
                self.cursor[doc_id] += 1
                am.append(int(rem.old_to_new[t]))
                offs.append(cache["l_sys"] + len(sub_sufs[r]))
            return _FakeArray(np.zeros((len(sub_sufs), 1, len(rem.kept_old_ids)), dtype=np.float32)), _FakeArray(am), offs

        def forward_early14_slot(self, toks, cache, off_b, slot_idx):
            pass

        def forward_decode_step_slot(self, toks, cache, off_b, slot_idx, *, n_keep, return_logits=False):
            am = []
            for r in range(n_keep):
                d = self.slot_doc[int(slot_idx.data[r])]
                seq = self.scripts[d]
                idx = min(self.cursor[d], len(seq) - 1)
                self.cursor[d] += 1
                t = seq[idx]
                am.append(int(rem.old_to_new[t]))
            return _FakeArray(np.zeros((n_keep, 1, len(rem.kept_old_ids)), dtype=np.float32)), _FakeArray(am)

    import threading

    eng = FastGemma4Engine.__new__(FastGemma4Engine)
    eng._gpu_lock = threading.Lock()
    eng.tokenizer = tok
    eng._prefix_cache = {}
    eng.max_prefix_cache = 4
    eng._ane_workers = {}
    eng.model = _MockModel({0: tok_ttf, 1: tok_open})  # type: ignore[assignment]
    eng.get_prefix_kv = lambda sys_ids: {"l_sys": len(sys_ids), "k_sys": [], "v_sys": []}  # type: ignore[method-assign]

    v6 = PythonicEngineV6(eng)
    assert isinstance(tok.apply_chat_template([{"role": "user", "content": "hi"}], tokenize=False), str)

    records = [
        {"filename": "HHRG-118-SY00-TTF-HollowayM-20240522.pdf", "text": "Truth in Testimony Disclosure Marcus Holloway."},
        {"filename": "HHRG-118-GO00-Transcript-20240522.pdf", "text": "Full oversight committee hearing transcript on agency operations " * 6},
    ]
    monkeypatch.setattr(fg4_spec, "mx", fake_mx)
    out = v6.run_records(records, use_zero_llm_bypass=False, short_circuit_triage=False)
    assert len(out["clean_objs"]) == 2
    assert out["clean_objs"][0]["primary_kind"] == "truth_in_testimony_disclosure"
    assert out["clean_objs"][1]["primary_kind"] == "hearing_transcript"




def test_rolling_doc_order_and_pick_valid_token_sampling_kwargs() -> None:
    """`compute_rolling_doc_order` + `PerDocGrammarHelperV6.pick_valid_token` sampling kwargs."""
    import numpy as np

    sufs = [[1, 2], [1, 2, 3, 4, 5, 6]]
    order = compute_rolling_doc_order(sufs, b_slots=1, sort_by_length=True)
    assert order == [1, 0]

    paths = resolve_paths()
    tok = FastGemma4Tokenizer(paths.resolve_tokenizer_json())
    rem = VocabRemapper.load_or_build(paths.resolve_tokenizer_json(), paths.vocab_remap_npz)
    gh_std = GrammarHelper(tok, SCHEMA_V4_STR, rem.kept_old_ids, whitespace_flexible=False)
    helper = PerDocGrammarHelperV6(
        gh_std,
        doc_order=order,
        doc_target_kinds={0: "truth_in_testimony_disclosure"},
        sync_ff_with_std=True,
    )
    m_first = helper.new_matcher()   # corresponds to doc 1 (unlocked)
    m_second = helper.new_matcher()  # corresponds to doc 0 (locked TTF)
    assert not isinstance(m_first, SyncKindMatcher)
    assert isinstance(m_second, SyncKindMatcher)
    assert helper.dispatched_doc_indices == [1, 0]

    # Force fallback path with `temperature=0.5, top_p=0.9` kwargs on `SyncKindMatcher`
    logits_row = np.zeros(len(rem.kept_old_ids), dtype=np.float32)
    picked_tok, was_masked = helper.pick_valid_token(
        m_second,
        logits_row,
        0,
        temperature=0.5,
        top_p=0.9,
    )
    assert isinstance(picked_tok, int)
    assert isinstance(was_masked, bool)



def test_parquet_runner_v6_crash_resume_verifier_pass2_and_cli(tmp_path: Path) -> None:
    """Verify `run_docmeta_parquet_sweep` atomic `.tmp` crash recovery, `link_key_hex` resume, verifier hook, and Pass-2."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    from congress_docmeta.cli import build_parser
    from congress_docmeta import run_docmeta_parquet_sweep

    # 1. Verify CLI `docmeta-sweep` parser
    parser = build_parser()
    parsed_args = parser.parse_args(
        [
            "docmeta-sweep",
            "in.parquet",
            "out.parquet",
            "--chunk-rows",
            "1024",
            "--b-slots",
            "64",
            "--use-ane-ring",
            "true",
            "--embed-ane",
            "bge-small",
            "--escalate-gpt-oss",
            "--resume",
        ]
    )
    assert parsed_args.chunk_rows == 1024
    assert parsed_args.b_slots == 64
    assert parsed_args.use_ane_ring == "true"
    assert parsed_args.embed_ane == "bge-small"
    assert parsed_args.escalate_gpt_oss is True
    assert parsed_args.resume is True

    # 2. Build 10-row synthetic `llm_queue_v6_2`-shaped Parquet (including 1 empty row -> `0` skip_empty loss)
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

    class _FakeSweepEngine:
        def __init__(self) -> None:
            self.tokenizer = tok
            self.new_to_old = rem.kept_old_ids
            self.calls: list[dict[str, Any]] = []

        def run_rolling(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            n = len(kwargs["suf_ids_list"])
            gh = kwargs["gh"]
            for doc_i in range(n):
                if hasattr(gh, "new_matcher_for_doc"):
                    gh.new_matcher_for_doc(doc_i)
            return {
                "gen_toks": [list(gen_suffix_ids) for _ in range(n)],
                "prefill_sec": 0.01,
                "decode_sec": 0.02,
                "mask_fallbacks": 0,
                "llm_steps": 10,
                "ff_early14_steps": 2,
            }

    class _FakeGptOssItem:
        def __init__(self, obj: dict[str, Any]) -> None:
            self.parsed = obj
            self.text = json.dumps(obj, separators=(",", ":"))

    class _FakeGptOssBatch:
        def __init__(self, items: list[_FakeGptOssItem]) -> None:
            self.items = items

    class _FakeGptOssEngine:
        def generate_batch(self, prompts: list[str], *, per_doc_grammars: Any = None, **kwargs: Any) -> _FakeGptOssBatch:
            assert per_doc_grammars is not None and len(per_doc_grammars) == len(prompts)
            repaired = {
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
            }
            return _FakeGptOssBatch([_FakeGptOssItem(repaired) for _ in prompts])

    queue_rows = []
    for i in range(10):
        lk = f"{i + 1:016x}"
        sb = f"{i + 1:064x}"
        is_empty = i == 2
        queue_rows.append(
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
                "v6_route": "tier1_or_cover_or_anchor_grammar_locked" if i % 2 == 0 else "deterministic_enriched_open_kind",
                "filename": f"HHRG-118-SY00-Wstate-DoeJ-202405{i + 10:02d}.pdf",
                "effective_format": "pdf",
                "text_source": "body_text_ssot_v12_head_tail_9000",
                "p12_raw_text": "" if is_empty else "Statement of Jane Doe before the House Committee on Science, Space, and Technology on electric grid reliability.",
                "p12_clean_text": "" if is_empty else "Statement of Jane Doe before the House Committee on Science, Space, and Technology on electric grid reliability.",
                "known_json": json.dumps({"congress": 118, "cmt": ["hssy00"], "chambers": ["house"]}),
                "locked_primary_kind": "witness_statement" if i % 2 == 0 else None,
                "grammar_lock_source": "cover_lock" if i % 2 == 0 else None,
                "lock_id": "wstate_lock" if i % 2 == 0 else None,
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

    in_pq = tmp_path / "queue_v6_2.parquet"
    out_pq = tmp_path / "llm_results_v6_2.parquet"
    pq.write_table(pa.Table.from_pylist(queue_rows), in_pq)

    fake_eng = _FakeSweepEngine()

    def _crash_after_first_chunk(shard_idx: int, _part_path: Path) -> None:
        if shard_idx == 0:
            raise RuntimeError("Simulated mid-sweep interruption after shard 0")

    with pytest.raises(RuntimeError, match="Simulated mid-sweep interruption"):
        run_docmeta_parquet_sweep(
            fake_eng,
            in_pq,
            out_pq,
            chunk_rows=4,
            b_slots=4,
            use_ane_ring=True,
            _after_chunk_hook=_crash_after_first_chunk,
        )

    parts_dir = tmp_path / "llm_results_v6_2.parts"
    assert (parts_dir / "part-00000.parquet").is_file()
    assert not out_pq.exists()
    # Plant a simulated torn `.tmp` file and verify `resume=True` unlinks it cleanly
    stale_tmp = parts_dir / ".part-00001.parquet.tmp"
    stale_tmp.write_bytes(b"corrupt partial parquet bytes")

    def _flag_first_row_verifier(objs: Any, rows: Any) -> list[Any]:
        return [{"is_faithful": idx != 0, "score": 0.12 if idx == 0 else 0.96} for idx in range(len(objs))]

    resumed = run_docmeta_parquet_sweep(
        fake_eng,
        in_pq,
        out_pq,
        chunk_rows=4,
        b_slots=4,
        use_ane_ring=True,
        resume=True,
        external_verifier=_flag_first_row_verifier,
        escalate_gpt_oss=True,
        gpt_oss_engine=_FakeGptOssEngine(),
    )
    assert not stale_tmp.exists()
    assert resumed.docs_skipped_resume == 4
    assert resumed.docs_processed == 6
    assert resumed.pass2_escalated_docs == 2  # 1 per remaining chunk (chunk 1 & chunk 2)
    assert resumed.pass2_accepted_docs == 2
    assert out_pq.is_file()
    assert fake_eng.calls[-1]["use_ane_ring"] is True

    final_tbl = pq.read_table(out_pq)
    assert final_tbl.num_rows == 10  # Exact row conservation across crash + resume + empty-text guard!
    out_rows = final_tbl.to_pylist()
    assert {r["link_key_hex"] for r in out_rows} == {r["link_key_hex"] for r in queue_rows}
    assert all(r["strict_v4_valid"] is True for r in out_rows)
    empty_row_out = next(r for r in out_rows if r["list_row"] == 2)
    assert empty_row_out["status"] == "stub_or_blank"
    p2_rows = [r for r in out_rows if r["pass2_escalated"] is True]
    assert len(p2_rows) == 2
    assert all(r["docmeta_source"] == "fast-gpt-oss-20b-pass2" and r["pass1_docmeta_json"] for r in p2_rows)
