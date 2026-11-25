"""Offline unit & integration tests for DocMeta V7.2 3-family labeling factory (`ct-02x5`)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Any

import numpy as np
import pytest

from congress_docmeta.v7.factory.cache import (
    CacheKey,
    SixTupleCache,
    default_cache_path,
    make_cache_key,
)
from congress_docmeta.v7.factory.counterfactual import (
    perturb_corrupt_to_error_stub,
    perturb_delete_dates_and_orgs,
    perturb_misleading_filename,
    perturb_prepend_packet_cover,
    perturb_strip_present_header,
    run_counterfactual_suite,
    synthesize_counterfactual_cases,
)
from congress_docmeta.v7.factory.grounding import (
    adjudicate_three_family,
    format_deadlock_digest,
    repair_span_refs_in_payload,
    run_checkeval_arbiter,
    verify_span_grounding,
)
from congress_docmeta.v7.factory.pilot import (
    CORE_TRIAGE_SCHEMA,
    _parse_and_validate,
    build_live_sota_checkeval_fn,
    extract_blind_text_from_ssot_row,
    main as pilot_main,
    run_pilot,
    stratify_pilot_sample,
)
from congress_docmeta.v7.factory.runners import (
    AdapterOutput,
    RunnerConfig,
    UsageGuard,
    _prepare_stripped_codex_home,
    build_agy_command,
    build_claude_command,
    build_codex_command,
    build_gemini_command,
    default_parse_fn,
    extract_json_payload,
    parse_claude_stream_json,
    read_codex_rollout_rate_limits,
    run_family_with_cache,
    run_three_family_parallel,
)
from congress_docmeta.v7.factory.splits import (
    audit_decontamination,
    build_event_temporal_splits,
    compute_agreement_metrics,
    extract_event_group_key,
)


# ---------------------------------------------------------------------------
# 1. SixTupleCache & parse() decoupling
# ---------------------------------------------------------------------------


def test_default_cache_path_lives_under_archive_release() -> None:
    p = default_cache_path()
    assert p.parts[-4:] == (".cache", "archive-release", "docmeta-v7-factory", "cache.sqlite")


def test_six_tuple_cache_hit_miss_and_parse_replay_zero_invocations(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.sqlite"
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    prompt = "Extract DocMeta:\nDocument Text:\nHearing on AI oversight May 14, 2025."
    doc_text = "Hearing on AI oversight May 14, 2025."

    call_count = 0

    def mock_adapter(p: str, s: dict[str, Any], *, model_id: str, timeout_s: float) -> str:
        nonlocal call_count
        call_count += 1
        return (
            '{"status":"usable","media_format":"prose","is_packet":false,'
            '"primary_genre":"hearing_notice","title_span":{"quote":"AI oversight","start":0,"end":5}}'
        )

    def parse_v1(raw: str) -> dict[str, Any]:
        return default_parse_fn(raw)

    def parse_v2_with_repair(raw: str) -> dict[str, Any]:
        parsed = default_parse_fn(raw)
        parsed = repair_span_refs_in_payload(doc_text, parsed)
        parsed["normalized_by"] = "parse_v2"
        return parsed

    with SixTupleCache(db_path) as cache:
        r1 = run_family_with_cache(
            family="claude",
            input_text=doc_text,
            prompt_text=prompt,
            schema=schema,
            codebook_version="v7.0",
            cache=cache,
            parse_fn=parse_v1,
            adapters={"claude": mock_adapter},
        )
        assert r1.ok is True
        assert r1.cache_hit is False
        assert call_count == 1
        assert r1.parsed is not None
        assert r1.parsed["title_span"]["start"] == 0

        # Replay with completely rewritten `parse_v2_with_repair`: 100% cache hit, 0 invocations!
        r2 = run_family_with_cache(
            family="claude",
            input_text=doc_text,
            prompt_text=prompt,
            schema=schema,
            codebook_version="v7.0",
            cache=cache,
            parse_fn=parse_v2_with_repair,
            adapters={"claude": mock_adapter},
        )
        assert r2.ok is True
        assert r2.cache_hit is True
        assert call_count == 1
        assert r2.parsed is not None
        assert r2.parsed["normalized_by"] == "parse_v2"
        # Offset auto-repaired purely in parse_v2!
        assert r2.parsed["title_span"] == {"quote": "AI oversight", "start": 11, "end": 23}

        # Changing any of the 6 tuple dimensions causes a cache miss.
        for mod_kwargs in [
            {"input_text": doc_text + " "},
            {"codebook_version": "v7.1"},
            {"model_id": "claude-opus-custom"},
            {"prompt_text": prompt + " "},
            {"schema": {"type": "object", "properties": {"status": {"type": "string"}, "x": {"type": "string"}}}},
            {"slice_spec": "p1_only"},
        ]:
            kwargs: dict[str, Any] = {
                "family": "claude",
                "input_text": doc_text,
                "prompt_text": prompt,
                "schema": schema,
                "codebook_version": "v7.0",
                "cache": cache,
                "parse_fn": parse_v1,
                "adapters": {"claude": mock_adapter},
            }
            kwargs.update(mod_kwargs)
            miss_res = run_family_with_cache(**kwargs)
            assert miss_res.cache_hit is False

        assert call_count == 7
        assert cache.count() == 7


def test_bounded_parse_retry_increments_rollout_id(tmp_path: Path) -> None:
    db_path = tmp_path / "retry_cache.sqlite"
    attempts: list[int] = []

    def flaky_adapter(
        prompt: str,
        schema: dict[str, Any],
        *,
        model_id: str,
        timeout_s: float,
        rollout_id: int = 0,
    ) -> str:
        attempts.append(rollout_id)
        if rollout_id == 0:
            return "not-json-garbage"
        return '{"status": "usable", "primary_genre": "witness_statement"}'

    cfg = RunnerConfig(max_parse_retries=2)
    with SixTupleCache(db_path) as cache:
        res = run_family_with_cache(
            family="codex",
            input_text="Testimony of Jane Doe",
            prompt_text="Prompt",
            schema={"type": "object"},
            codebook_version="v7.0",
            cache=cache,
            config=cfg,
            adapters={"codex": flaky_adapter},
        )
        assert res.ok is True
        assert res.rollout_id == 1
        assert attempts == [0, 1]

        # Re-running hits cached rollout_id=0 (fail parse) -> cached rollout_id=1 (success), 0 new calls!
        res2 = run_family_with_cache(
            family="codex",
            input_text="Testimony of Jane Doe",
            prompt_text="Prompt",
            schema={"type": "object"},
            codebook_version="v7.0",
            cache=cache,
            config=cfg,
            adapters={"codex": flaky_adapter},
        )
        assert res2.ok is True
        assert res2.cache_hit is True
        assert res2.rollout_id == 1
        assert attempts == [0, 1]


def test_nonzero_timeout_does_not_burn_parse_retries(tmp_path: Path) -> None:
    db_path = tmp_path / "timeout_retry.sqlite"
    attempts: list[int] = []

    def timeout_adapter(
        prompt: str,
        schema: dict[str, Any],
        *,
        model_id: str,
        timeout_s: float,
        rollout_id: int = 0,
    ) -> AdapterOutput:
        attempts.append(rollout_id)
        return AdapterOutput(raw_text="", returncode=-1, error="timeout after 1.0s")

    cfg = RunnerConfig(max_parse_retries=2)
    with SixTupleCache(db_path) as cache:
        res = run_family_with_cache(
            family="codex",
            input_text="Sample timeout text",
            prompt_text="Prompt",
            schema={"type": "object"},
            codebook_version="v7.0",
            cache=cache,
            config=cfg,
            adapters={"codex": timeout_adapter},
        )
    assert res.ok is False
    assert res.returncode == -1
    assert res.error == "timeout after 1.0s"
    assert attempts == [0]


# ---------------------------------------------------------------------------
# 2. CLI command builders, payload unwrapping, and 3-family parallel runner
# ---------------------------------------------------------------------------


def test_cli_command_builders_verified_flags(tmp_path: Path) -> None:
    schema = {"type": "object", "properties": {"status": {"type": "string"}}}
    claude_cmd = build_claude_command(schema, model="sonnet")
    assert claude_cmd[0].endswith("claude")
    assert "-p" in claude_cmd
    assert "--output-format" in claude_cmd and claude_cmd[claude_cmd.index("--output-format") + 1] == "json"
    assert "--json-schema" in claude_cmd
    assert "--tools" in claude_cmd and claude_cmd[claude_cmd.index("--tools") + 1] == ""
    assert "--permission-mode" in claude_cmd and claude_cmd[claude_cmd.index("--permission-mode") + 1] == "plan"
    assert "--no-session-persistence" in claude_cmd
    assert "--model" in claude_cmd and claude_cmd[claude_cmd.index("--model") + 1] == "sonnet"

    sp = tmp_path / "schema.json"
    op = tmp_path / "out.json"
    codex_cmd = build_codex_command(sp, op, model="o3")
    assert codex_cmd[:2][1] == "exec"
    assert "-s" in codex_cmd and codex_cmd[codex_cmd.index("-s") + 1] == "read-only"
    assert "--ephemeral" in codex_cmd
    assert "--skip-git-repo-check" in codex_cmd
    assert "--output-schema" in codex_cmd and codex_cmd[codex_cmd.index("--output-schema") + 1] == str(sp)
    assert "-o" in codex_cmd and codex_cmd[codex_cmd.index("-o") + 1] == str(op)
    assert codex_cmd[-1] == "-"

    gemini_cmd = build_gemini_command("Return JSON", model="gemini-2.5-pro")
    assert "-p" in gemini_cmd and gemini_cmd[gemini_cmd.index("-p") + 1] == "Return JSON"
    assert "-o" in gemini_cmd and gemini_cmd[gemini_cmd.index("-o") + 1] == "json"
    assert "--approval-mode" in gemini_cmd and gemini_cmd[gemini_cmd.index("--approval-mode") + 1] == "plan"
    assert "-m" in gemini_cmd and gemini_cmd[gemini_cmd.index("-m") + 1] == "gemini-2.5-pro"

    agy_cmd = build_agy_command("Prompt text", sp, model="gemini-4-carbon-medium")
    assert agy_cmd[0].endswith("agy")
    assert "-p" in agy_cmd and agy_cmd[agy_cmd.index("-p") + 1] == "Prompt text"
    assert "--output-format" in agy_cmd and agy_cmd[agy_cmd.index("--output-format") + 1] == "json"
    assert "--json-schema" in agy_cmd and agy_cmd[agy_cmd.index("--json-schema") + 1] == str(sp)
    assert "--mode" in agy_cmd and agy_cmd[agy_cmd.index("--mode") + 1] == "plan"
    assert "--disable-slash-commands" in agy_cmd
    assert "--model" in agy_cmd and agy_cmd[agy_cmd.index("--model") + 1] == "gemini-4-carbon-medium"


def test_extract_json_payload_envelopes_and_fences() -> None:
    claude_raw = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "",
            "structured_output": {"status": "usable", "primary_genre": "hearing_notice"},
        }
    )
    _, claude_obj = extract_json_payload(claude_raw, provider="claude_cli")
    assert claude_obj == {"status": "usable", "primary_genre": "hearing_notice"}

    gemini_raw = json.dumps(
        {
            "session_id": "abc",
            "response": "Here is the JSON:\n```json\n{\"status\": \"usable\", \"primary_genre\": \"qfr_document\"}\n```",
            "stats": {"tokens": 100},
        }
    )
    _, gemini_obj = extract_json_payload(gemini_raw, provider="gemini_cli")
    assert gemini_obj == {"status": "usable", "primary_genre": "qfr_document"}

    claude_err = json.dumps({"type": "result", "is_error": True, "result": "quota exceeded"})
    with pytest.raises(ValueError):
        extract_json_payload(claude_err, provider="claude_cli")

    agy_raw = json.dumps(
        {
            "conversation_id": "ad0a0bed-4d21-4b97-a2f6-a4f38c391541",
            "status": "SUCCESS",
            "response": '{"status":"usable"}',
            "structured_output": {"status": "usable", "primary_genre": "witness_testimony"},
        }
    )
    _, agy_obj = extract_json_payload(agy_raw, provider="agy_cli")
    assert agy_obj == {"status": "usable", "primary_genre": "witness_testimony"}

    agy_err = json.dumps({"conversation_id": "x", "status": "FAILED", "error": "bad schema"})
    with pytest.raises(ValueError):
        extract_json_payload(agy_err, provider="agy_cli")


def test_run_three_family_parallel_and_timeout(tmp_path: Path) -> None:
    def make_ok(genre: str) -> Any:
        def _fn(prompt: str, schema: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            time.sleep(0.01)
            return {
                "status": "usable",
                "media_format": "prose",
                "is_packet": False,
                "primary_genre": genre,
            }

        return _fn

    adapters = {
        "claude": make_ok("witness_statement"),
        "codex": make_ok("witness_statement"),
        "gemini": make_ok("witness_statement"),
    }

    with SixTupleCache(tmp_path / "p.sqlite") as cache:
        res = run_three_family_parallel(
            input_text="Testimony of Alice",
            prompt_text="Prompt",
            schema={"type": "object"},
            codebook_version="v7.0",
            cache=cache,
            adapters=adapters,
        )
        assert list(res.keys()) == ["claude", "codex", "gemini"]
        assert all(r.ok and not r.cache_hit for r in res.values())

        # Timeout test via real Python CLI override.
        timeout_cfg = RunnerConfig(
            gemini_bin=sys.executable,
            provider_overrides={"gemini": "gemini_cli"},
            timeout_s=0.1,
            max_parse_retries=0,
        )
        # Note: invoking python -p ... errors immediately or times out cleanly without crashing.
        err_res = run_family_with_cache(
            family="gemini",
            input_text="x",
            prompt_text="y",
            schema={"type": "object"},
            codebook_version="v7.0",
            cache=cache,
            config=timeout_cfg,
        )
        assert err_res.ok is False
        assert err_res.returncode != 0


# ---------------------------------------------------------------------------
# 3. SpanRef grounding & entity/title/date/org verification
# ---------------------------------------------------------------------------


def test_verify_span_grounding_accepts_grounded_and_rejects_hallucinations() -> None:
    text = (
        "Committee on Oversight and Reform\n"
        "Hearing on Federal Energy Forecasts\n"
        "January 13, 2022\n"
        "Testimony of Dr. Jane A. Doe, IRS\n"
        "Also appearing: Alice Johnson and Robert Smith.\n"
    )
    start_title = text.index("Hearing on Federal Energy Forecasts")
    end_title = start_title + len("Hearing on Federal Energy Forecasts")

    good_payload = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "witness_statement",
        "verbatim_title": "Hearing on Federal Energy Forecasts",
        "title_span": {"quote": "Hearing on Federal Energy Forecasts", "start": start_title, "end": end_title},
        "date_spans": ["January 13, 2022"],
        "doc_date": "2022-01-13",
        "issuer_org": "IRS",
        "personas": [{"name": "Jane A. Doe", "role": "witness"}],
    }
    gr_ok = verify_span_grounding(text, good_payload)
    assert gr_ok.passed is True
    assert gr_ok.errors == []
    assert gr_ok.checked_spans == 1

    # 1) Reject out-of-bounds SpanRef & mismatched quote.
    bad_span = {
        **good_payload,
        "title_span": {"quote": "Hearing on Federal Energy Forecasts", "start": 0, "end": 9999},
    }
    assert not verify_span_grounding(text, bad_span).passed

    # 2) Reject ungrounded ISO date leakage in `date_spans`.
    iso_leak = {**good_payload, "date_spans": ["2022-01-13"]}
    gr_iso = verify_span_grounding(text, iso_leak)
    assert not gr_iso.passed
    assert any(e.reason == "ungrounded_date_span" for e in gr_iso.errors)

    # 3) Reject unmentioned acronym expansion in `issuer_org`.
    acronym_exp = {**good_payload, "issuer_org": "Internal Revenue Service"}
    gr_org = verify_span_grounding(text, acronym_exp)
    assert not gr_org.passed
    assert any(e.reason == "ungrounded_issuer_org" for e in gr_org.errors)

    # 4) Reject ungrounded / cross-merged persona name (`Alice Smith` doesn't appear together).
    bad_persona = {**good_payload, "personas": [{"name": "Alice Smith", "role": "witness"}]}
    gr_pers = verify_span_grounding(text, bad_persona)
    assert not gr_pers.passed
    assert any(e.reason == "ungrounded_person_name" for e in gr_pers.errors)

    # 5) Reject synthesized title.
    synth_title = {**good_payload, "verbatim_title": "Federal Energy Forecasts — Committee on Oversight"}
    gr_title = verify_span_grounding(text, synth_title)
    assert not gr_title.passed
    assert any(e.reason == "ungrounded_verbatim_title" for e in gr_title.errors)

    # 6) Enforce status != usable => primary_genre is None.
    bad_status = {"status": "stub_or_blank", "media_format": None, "is_packet": False, "primary_genre": "witness_statement"}
    gr_st = verify_span_grounding(text, bad_status)
    assert not gr_st.passed
    assert any(e.reason == "non_usable_status_must_have_null_primary_genre" for e in gr_st.errors)

    # 7) Valid non-usable with primary_genre=None passes.
    good_non_usable = {"status": "stub_or_blank", "media_format": None, "is_packet": False, "primary_genre": None}
    assert verify_span_grounding(text, good_non_usable).passed


def test_repair_span_refs_pure_helper() -> None:
    text = "Prefix text.\nQuestions for the   Record\nSuffix."
    broken = {"title_span": {"quote": "Questions for the Record", "start": 0, "end": 5}}
    repaired = repair_span_refs_in_payload(text, broken)
    assert verify_span_grounding(text, repaired).passed is True
    assert repaired["title_span"]["start"] == text.index("Questions")

    # Non-existent quote must NOT be repaired into passing.
    hallucinated = {"title_span": {"quote": "Totally Fabricated Title", "start": 0, "end": 10}}
    repaired_hall = repair_span_refs_in_payload(text, hallucinated)
    assert verify_span_grounding(text, repaired_hall).passed is False


# ---------------------------------------------------------------------------
# 4. Consensus, CheckEval 2-vs-1, and 3-way deadlock Markdown digest
# ---------------------------------------------------------------------------


def test_adjudicate_three_family_consensus_checkeval_and_deadlock() -> None:
    text = (
        "Questions for the Record\n"
        "Submitted by Chairman Comer to Dr. Elena Patel\n"
        "Question 1: What are the cost projections for FY 2025?\n"
        "Response: Our baseline estimate remains unchanged."
    )
    qfr = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "qfr_document",
        "personas": [{"name": "Dr. Elena Patel", "role": "witness"}],
        "verbatim_title": "Questions for the Record",
    }
    ws = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "witness_statement",
        "personas": [{"name": "Dr. Elena Patel", "role": "witness"}],
        "verbatim_title": "Questions for the Record",
    }

    # Case A: 3/3 match + grounded -> auto_accept_gold.
    d_unanimous = adjudicate_three_family(text, {"claude": qfr, "codex": qfr, "gemini": qfr}, doc_key="d1")
    assert d_unanimous.verdict == "auto_accept_gold"
    assert d_unanimous.accepted_tuple == ("usable", "prose", False, "qfr_document")

    # Case B: 3/3 match with grounding failure -> deadlock_needs_owner.
    ungrounded_qfr = {**qfr, "issuer_org": "Department of Imaginary Affairs"}
    d_ungrounded = adjudicate_three_family(
        text, {"claude": ungrounded_qfr, "codex": qfr, "gemini": qfr}, doc_key="d_bad_gr"
    )
    assert d_ungrounded.verdict == "deadlock_needs_owner"
    assert "grounding_failure" in (d_ungrounded.deadlock_reason or "")

    # Case C: 2 vs 1 resolved by CheckEval (even when the 1 minority is actually right!).
    def mock_checkeval(t: str, questions: list[Any], candidates: dict[str, Any], grouped: Any) -> dict[str, Any]:
        answers = []
        for q in questions:
            if q.target_value in ("qfr_document", "qfr"):
                answers.append({"qid": q.qid, "answer": True, "evidence_quote": "Questions for the Record"})
            else:
                answers.append({"qid": q.qid, "answer": False, "evidence_quote": None})
        return {"answers": answers}

    d_2v1 = adjudicate_three_family(
        text,
        {"claude": ws, "codex": ws, "gemini": qfr},
        doc_key="d2",
        check_eval_fn=mock_checkeval,
    )
    assert d_2v1.verdict == "checkeval_resolved"
    assert d_2v1.accepted_tuple == ("usable", "prose", False, "qfr_document")

    # Built-in offline CheckEval also resolves QFR cleanly from text evidence.
    d_2v1_auto = adjudicate_three_family(text, {"claude": ws, "codex": ws, "gemini": qfr}, doc_key="d2_auto")
    assert d_2v1_auto.verdict == "checkeval_resolved"
    assert d_2v1_auto.accepted_tuple == ("usable", "prose", False, "qfr_document")

    # CheckEval rejects ungrounded quote evidence and escalates to deadlock.
    def lying_checkeval(t: str, questions: list[Any], *args: Any) -> dict[str, Any]:
        return {
            "answers": [
                {"qid": q.qid, "answer": True, "evidence_quote": "Fabricated quote not in text"}
                for q in questions
            ]
        }

    d_lying = adjudicate_three_family(
        text,
        {"claude": ws, "codex": ws, "gemini": qfr},
        doc_key="d_lying",
        check_eval_fn=lying_checkeval,
    )
    assert d_lying.verdict == "deadlock_needs_owner"

    # Case D: 3-way deadlock -> deadlock_needs_owner + Markdown digest.
    notice = {**qfr, "primary_genre": "hearing_notice"}
    d_3way = adjudicate_three_family(
        text,
        {"claude": qfr, "codex": ws, "gemini": notice},
        doc_key="d3_way",
    )
    assert d_3way.verdict == "deadlock_needs_owner"
    assert d_3way.deadlock_reason == "three_way_deadlock"

    digest = format_deadlock_digest([d_ungrounded, d_3way])
    assert "# DocMeta V7 Deadlock Digest" in digest
    assert "d3_way" in digest
    assert "three_way_deadlock" in digest
    assert "| `claude` |" in digest


# ---------------------------------------------------------------------------
# 5. Event-grouped + 2026 temporal splits, decontamination & psychometrics
# ---------------------------------------------------------------------------


def test_event_temporal_splits_and_decontamination_zero_leakage() -> None:
    ev_key_1, dt_1 = extract_event_group_key({"filename": "HHRG-115-IF14-TTF-WingC-20170726.pdf"})
    ev_key_2, dt_2 = extract_event_group_key({"filename": "HHRG-115-IF14-20170726-SD001.pdf"})
    assert ev_key_1 == "house:115:IF14:20170726"
    assert ev_key_1 == ev_key_2
    assert dt_1 == (2017, 7, 26) == dt_2

    ev_crpt, dt_crpt = extract_event_group_key({"filename": "CRPT-119-BA00-Vote252-20260304.pdf"})
    assert ev_crpt == "crpt:119:BA00:20260304"
    assert dt_crpt == (2026, 3, 4)

    docs = [
        # Event A (2 docs from same House hearing must stay in the same split)
        {
            "doc_key": "a1",
            "filename": "HHRG-115-IF14-TTF-WingC-20170726.pdf",
            "text": "Rule XI Truth in Testimony disclosure form submitted by Charles Wing regarding Clean Air Act.",
            "doc_date": "2017-07-26",
        },
        {
            "doc_key": "a2",
            "filename": "HHRG-115-IF14-Wstate-WingC-20170726.pdf",
            "text": "Written testimony of Charles Wing before the Energy Subcommittee on grid resilience and storage.",
            "doc_date": "2017-07-26",
        },
        # Event B (completely distinct committee/date/topic)
        {
            "doc_key": "b1",
            "filename": "HHRG-117-JU00-WList-20210415.pdf",
            "text": "Witness list for Judiciary Committee hearing on antitrust enforcement in digital marketplaces.",
            "doc_date": "2021-04-15",
        },
        # Event C (unstructured filename, same Senate committee+event_date fallback)
        {
            "doc_key": "c1",
            "filename": "senate_doc_1.pdf",
            "chamber": "senate",
            "committees": ["Senate Committee on Finance"],
            "event_date": "2023-09-10",
            "text": "Opening statement of Chairman Wyden on prescription drug pricing transparency reforms.",
        },
        {
            "doc_key": "c2",
            "filename": "senate_doc_2.pdf",
            "chamber": "senate",
            "committees": ["Committee on Finance"],
            "event_date": "2023-09-10",
            "text": "Biographical summary of Dr. Maya Lin, health economics professor at Stanford University.",
        },
        # Event D (2026 temporal holdout)
        {
            "doc_key": "d2026",
            "filename": "CRPT-119-BA00-Vote252-20260304.pdf",
            "text": "Committee on Financial Services recorded vote number 252 ordered reported March 4, 2026.",
            "doc_date": "2026-03-04",
        },
    ]

    split_res = build_event_temporal_splits(docs, temporal_cutoff="2026-01-01", dev_fraction=0.35, seed=7)
    assert split_res.assignments["d2026"] == "sealed_temporal_2026"
    assert split_res.assignments["a1"] == split_res.assignments["a2"]
    assert split_res.assignments["c1"] == split_res.assignments["c2"]
    assert split_res.counts["train"] >= 1
    assert split_res.counts["dev_iter"] >= 1

    eval_docs = split_res.splits["dev_iter"] + split_res.splits["sealed_temporal_2026"]
    report = audit_decontamination(split_res.splits["train"], eval_docs)
    assert report.clean is True
    assert report.flagged_count == 0


def test_audit_decontamination_detects_ngram_tfidf_and_dense_leaks() -> None:
    base = (
        "The Subcommittee on Health of the Committee on Energy and Commerce held a legislative hearing "
        "today regarding Medicare telehealth reimbursement extensions and rural hospital access standards."
    )
    train_docs = [{"doc_key": "t1", "text": base}]
    # Paraphrased/copied 8/13-gram overlap + TF-IDF collision
    eval_docs = [
        {"doc_key": "e_dup", "split": "dev_iter", "text": base + " Additional closing line."},
        {
            "doc_key": "e_clean",
            "split": "dev_iter",
            "text": "Completely unrelated appropriations amendment regarding maritime port infrastructure dredging.",
        },
    ]

    def fake_embed_fn(texts: list[str]) -> np.ndarray:
        # Make e_dup have cosine 0.99 with t1, e_clean orthogonal
        vecs = []
        for idx, _ in enumerate(texts):
            if idx in (0, 1):
                vecs.append([1.0, 0.0])
            else:
                vecs.append([0.0, 1.0])
        return np.array(vecs, dtype=np.float32)

    report = audit_decontamination(train_docs, eval_docs, embed_fn=fake_embed_fn)
    assert report.clean is False
    assert report.minilm_checked is True
    assert report.flagged_count == 1
    flag = report.flagged_docs[0]
    assert flag.eval_doc_key == "e_dup"
    assert "ngram8_containment" in flag.reasons
    assert "ngram13_containment" in flag.reasons
    assert "tfidf_cosine" in flag.reasons
    assert "minilm_cosine" in flag.reasons


def test_compute_agreement_metrics_multiclass_kappa_and_gwet_ac1() -> None:
    y_true = ["A", "A", "A", "B", "B", "C"]
    y_pred = ["A", "A", "B", "B", "B", "C"]
    m = compute_agreement_metrics(y_true, y_pred)
    assert m["n_total"] == 6
    assert pytest.approx(m["accuracy"], abs=1e-6) == 5.0 / 6.0
    assert 0.0 < m["cohen_kappa"] < 1.0
    assert 0.0 < m["gwet_ac1"] < 1.0
    assert set(m["per_class"].keys()) == {"A", "B", "C"}
    assert m["confusion"]["A"] == {"A": 2, "B": 1}

    # Rare-class Kappa Paradox demonstration (99% majority class agreement):
    # binary/skewed kappa drops near 0 while Gwet's AC1 stays high (~0.989).
    skew_true = ["majority"] * 99 + ["rare"]
    skew_pred = ["majority"] * 100
    m_skew = compute_agreement_metrics(skew_true, skew_pred)
    assert m_skew["cohen_kappa"] == 0.0
    assert m_skew["gwet_ac1"] > 0.98
    assert m_skew["per_class"]["rare"]["f1"] == 0.0
    assert m_skew["per_class"]["rare"]["ac1"] > 0.98


# ---------------------------------------------------------------------------
# 6. Counterfactual flip suite
# ---------------------------------------------------------------------------


def test_counterfactual_suite_passes_blind_eval_and_catches_slug_bias() -> None:
    report = run_counterfactual_suite()
    assert report.total >= 10
    assert report.failed_count == 0
    assert report.pass_rate == 1.0

    # Verify a filename-biased evaluator fails misleading `-TTF-` counterfactual.
    cases = synthesize_counterfactual_cases()
    ttf_cases = [c for c in cases if c.kind == "misleading_ttf_filename"]
    assert ttf_cases

    def buggy_filename_biased_eval(text: str, *, filename: str, case: Any) -> dict[str, Any]:
        payload = dict(case.original_payload)
        if "-TTF-" in filename:
            payload["primary_genre"] = "truth_in_testimony_disclosure"
        return payload

    bad_report = run_counterfactual_suite(ttf_cases, eval_fn=buggy_filename_biased_eval)
    assert bad_report.failed_count == len(ttf_cases)
    assert any("fooled_by_ttf_slug" in r.details for r in bad_report.results)


# ---------------------------------------------------------------------------
# 7. Pilot blind text extraction, stratification & dry-run smoke test
# ---------------------------------------------------------------------------


def test_pilot_blind_text_extraction_stratification_and_dry_run(tmp_path: Path) -> None:
    ssot_file = tmp_path / "mini_ssot.jsonl"
    sample_rows = [
        {
            "doc_key": "doc_ttf_mismatch",
            "split": "train",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Extract Congressional p1-2 metadata...\n"
                        'Advisory known metadata: {"congress": 118, "cmt": ["hsed00"]}\n'
                        "Filename: HHRG-118-ED14-TTF-WineBanksJ-20240515.pdf\n"
                        "Text:\nCommittee on Education and the Workforce\n"
                        "May 15, 2024\nDear Dr. Jordan Wine-Banks:\nYou are invited to testify before the committee."
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps({"status": "usable", "primary_kind": "witness_invitation", "doc_date": "2024-05-15"}),
                },
            ],
        },
        {
            "doc_key": "doc_packet",
            "split": "train",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Advisory known metadata: {}\nFilename: 2025-03-05-HRG-Testimony.pdf\n"
                        "Text:\nCOMMITTEE PACKET\nTABLE OF CONTENTS\nDocument 1: Witness Statement\nDocument 2: Bio\n"
                        "Written statement of John Adams on grid modernization March 5, 2025."
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps({"status": "usable", "primary_kind": "multi_doc_packet", "doc_date": "2025-03-05"}),
                },
            ],
        },
        {
            "doc_key": "doc_slides",
            "split": "train",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Advisory known metadata: {}\nFilename: cyber_slides.pdf\n"
                        "Text:\nSlide 1: Cyber Workforce Strategy\n• Point 1\n• Point 2\n• Point 3\n• Point 4\n• Point 5\n"
                        "Written statement by Jane Smith."
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps({"status": "usable", "primary_kind": "slides_or_visual", "doc_date": "2025-02-10"}),
                },
            ],
        },
        {
            "doc_key": "doc_transcript_2026",
            "split": "train",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Advisory known metadata: {}\nFilename: HHRG-119-FA16-Transcript-20260212.pdf\n"
                        "Text:\nThe Committee met, pursuant to notice, at 10:00 a.m. in Room 2172.\n"
                        "February 12, 2026\nChairman Mast: The committee will come to order."
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps({"status": "usable", "primary_kind": "hearing_transcript", "doc_date": "2026-02-12"}),
                },
            ],
        },
        {
            "doc_key": "doc_stub",
            "split": "excluded",
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Advisory known metadata: {}\nFilename: empty.pdf\n"
                        "Text:\n403 Forbidden - Cloudflare Access Denied"
                    ),
                },
                {
                    "role": "assistant",
                    "content": json.dumps({"status": "error_or_block", "primary_kind": None}),
                },
            ],
        },
    ]

    with ssot_file.open("w", encoding="utf-8") as fh:
        for r in sample_rows:
            fh.write(json.dumps(r) + "\n")

    # Verify blind extraction strips Filename and Advisory metadata completely.
    blind_txt, sidecar = extract_blind_text_from_ssot_row(sample_rows[0])
    assert "Filename:" not in blind_txt
    assert "Advisory known metadata:" not in blind_txt
    assert "-TTF-" not in blind_txt
    assert sidecar["filename"] == "HHRG-118-ED14-TTF-WineBanksJ-20240515.pdf"

    out_dir = tmp_path / "pilot_out"
    res = run_pilot(
        ssot_path=ssot_file,
        out_dir=out_dir,
        limit=5,
        workers=2,
        dry_run=True,
    )
    summary = res["summary"]
    assert summary["total_docs"] == 5
    assert summary["consensus_resolved_rate"] == 1.0
    assert Path(res["summary_path"]).is_file()
    assert Path(res["gold_candidates_path"]).is_file()
    assert Path(res["deadlocks_path"]).is_file()

    gold_lines = [json.loads(ln) for ln in Path(res["gold_candidates_path"]).read_text(encoding="utf-8").splitlines() if ln]
    by_key = {g["doc_key"]: g["gold"] for g in gold_lines}
    assert by_key["doc_ttf_mismatch"]["primary_genre"] == "oversight_or_committee_letter"
    assert by_key["doc_packet"]["is_packet"] is True
    assert by_key["doc_slides"]["media_format"] == "slides"
    assert by_key["doc_transcript_2026"]["primary_genre"] == "hearing_transcript"
    assert by_key["doc_stub"]["status"] == "error_or_block"
    assert by_key["doc_stub"]["primary_genre"] is None
    assert summary["splits"]["counts"]["sealed_temporal_2026"] >= 1
    assert summary["decontamination"]["clean"] is True
    assert summary["counterfactual_suite"]["pass_rate"] == 1.0

    # Verify CLI entrypoint succeeds cleanly too.
    exit_code = pilot_main(
        [
            "--ssot-path",
            str(ssot_file),
            "--out-dir",
            str(tmp_path / "pilot_cli"),
            "--limit",
            "3",
            "--dry-run",
        ]
    )
    assert exit_code == 0


def test_pilot_runs_even_without_v7_models_or_codebook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def blocked_v7_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        if name in {"congress_docmeta.v7.models", "congress_docmeta.v7.codebook", "congress_docmeta.v7.crosswalk"}:
            raise ImportError(f"Simulated missing {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked_v7_import)
    ssot_file = tmp_path / "offline_ssot.jsonl"
    ssot_file.write_text(
        json.dumps(
            {
                "doc_key": "offline_1",
                "messages": [
                    {
                        "role": "user",
                        "content": "Filename: test.pdf\nText:\nWritten statement of Alice Smith on May 5, 2025.",
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps({"status": "usable", "primary_kind": "witness_statement"}),
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    res = run_pilot(ssot_path=ssot_file, out_dir=tmp_path / "out", limit=1, dry_run=True)
    assert res["summary"]["total_docs"] == 1
    assert res["summary"]["consensus_resolved_rate"] == 1.0


def test_post_smoke_ocr_grounding_rationale_clamp_codex_reasoning_and_checkeval_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from congress_docmeta.v7.models import CoreEnvelopeExtraction

    # 1) OCR fuzzy span grounding in verify_span_grounding
    text = "Prepared Statement of Richand Muniz\nOrganization: IRS\n"
    start = text.index("Richand Muniz")
    end = start + len("Richand Muniz")

    ok_ocr = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "witness_testimony",
        "personas": [
            {
                "name": "Richard Muniz",
                "name_span": {"quote": "Richand Muniz", "start": start, "end": end},
                "role": "witness",
            }
        ],
    }
    assert verify_span_grounding(text, ok_ocr).passed is True

    # Missing name_span for OCR-altered name must fail grounding.
    no_span_ocr = {
        **ok_ocr,
        "personas": [{"name": "Richard Muniz", "role": "witness"}],
    }
    gr_missing = verify_span_grounding(text, no_span_ocr)
    assert gr_missing.passed is False
    assert any(e.reason == "ungrounded_person_name" for e in gr_missing.errors)

    # Acronym expansion without verbatim mention must still fail grounding.
    bad_org = {**ok_ocr, "issuer_org": "Internal Revenue Service"}
    gr_org = verify_span_grounding(text, bad_org)
    assert gr_org.passed is False
    assert any(e.reason == "ungrounded_issuer_org" for e in gr_org.errors)

    # 2) _parse_and_validate clamps >480 char rationale and validates CoreEnvelopeExtraction
    long_rationale = "X" * 520
    raw_json = json.dumps(
        {
            "rationale": long_rationale,
            "status": "usable",
            "media_format": "prose",
            "is_packet": False,
            "contains_genres": [],
            "primary_genre": "witness_testimony",
            "specialist_family": "testimony_bio_disclosure",
            "subkind": None,
            "verbatim_title": None,
            "title_span": None,
            "doc_date": None,
            "date_spans": [],
            "chamber": None,
            "congress": None,
            "committees": [],
            "subcommittees": [],
            "gist": None,
            "topics": [],
        }
    )
    parsed = _parse_and_validate(raw_json, text, model_cls=CoreEnvelopeExtraction)
    assert len(parsed["rationale"]) <= 480
    assert parsed["rationale"].endswith("...")

    # 3) RunnerConfig codex_reasoning_effort & build_codex_command flags
    cfg = RunnerConfig(codex_reasoning_effort="low")
    assert cfg.model_id_for("codex") == "codex-default:effort=low"
    cmd = build_codex_command(tmp_path / "schema.json", tmp_path / "out.json", reasoning_effort="low")
    c_idx = cmd.index("-c")
    assert cmd[c_idx + 1] == 'model_reasoning_effort="low"'

    # 4) build_live_sota_checkeval_fn mocked invocation & explicit_winner ungrounded guard
    import congress_docmeta.v7.factory.runners as runners_mod
    from congress_docmeta.v7.factory.runners import FamilyRunResult

    qfr_text = (
        "Questions for the Record\n"
        "Submitted by Chairman to Dr. Elena Patel\n"
        "Question 1: Budget status?\n"
        "Response: Unchanged."
    )
    qfr = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "qfr_correspondence",
    }
    ws = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "witness_testimony",
    }

    captured_calls: list[dict[str, Any]] = []

    def fake_run_family_with_cache(**kwargs: Any) -> FamilyRunResult:
        captured_calls.append(kwargs)
        return FamilyRunResult(
            family=kwargs["family"],
            model_id="claude-mock",
            cache_hit=False,
            rollout_id=0,
            ok=True,
            raw_text="{}",
            extracted_json_str="{}",
            parsed={
                "answers": [
                    {"qid": "q_genre_minority", "answer": True, "evidence_quote": "Questions for the Record"},
                    {"qid": "q_neg_qfr_boundary", "answer": True, "evidence_quote": "Question 1: Budget status?"},
                    {"qid": "q_genre_majority", "answer": False, "evidence_quote": None},
                ],
                "winner": "minority",
            },
            latency_ms=1.0,
            returncode=0,
            error=None,
            cache_key=CacheKey("a", "b", "c", "d", "e", "f"),
        )

    monkeypatch.setattr(runners_mod, "run_family_with_cache", fake_run_family_with_cache)
    with SixTupleCache(tmp_path / "ce.sqlite") as cache:
        ce_fn = build_live_sota_checkeval_fn(cache, "v7.0", cfg, arbiter_family="claude")
        decision = adjudicate_three_family(
            qfr_text,
            {"claude": ws, "codex": ws, "gemini": qfr},
            doc_key="ce_live_mock",
            check_eval_fn=ce_fn,
        )
    assert len(captured_calls) == 1
    assert captured_calls[0]["stage"] == "checkeval_arbiter"
    assert decision.verdict == "checkeval_resolved"
    assert decision.accepted_tuple == ("usable", "prose", False, "qfr_correspondence")

    # Guard: explicit_winner="majority" with fabricated evidence_quote MUST escalate to deadlock_needs_owner.
    def lying_explicit_winner(t: str, questions: list[Any], *args: Any) -> dict[str, Any]:
        return {
            "winner": "majority",
            "answers": [
                {
                    "qid": q.qid,
                    "answer": True,
                    "evidence_quote": "Totally fabricated quote absent from document text",
                }
                for q in questions
            ],
        }

    bad_decision = adjudicate_three_family(
        qfr_text,
        {"claude": ws, "codex": ws, "gemini": qfr},
        doc_key="ce_lying_winner",
        check_eval_fn=lying_explicit_winner,
    )
    assert bad_decision.verdict == "deadlock_needs_owner"
    assert bad_decision.checkeval is not None
    assert bad_decision.checkeval.resolved is False


def test_paired_checkeval_resolves_media_format_and_packet_splits() -> None:
    # 1) THOMAS HTML wrapped transcript: prose vs web_page -> resolves to web_page.
    thomas_text = (
        "The Library of Congress > THOMAS Home > Committee Reports > Search Results\n"
        "THIS SEARCH THIS DOCUMENT GOTO Next Hit\n"
        "XX. PROCEEDINGS OF THE FULL COMMITTEE MARKUP ON H.R. 1126\n"
        "The Committee met at 10:00 a.m."
    )
    tr_prose = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "hearing_transcript",
    }
    tr_web = {**tr_prose, "media_format": "web_page"}
    d_web = adjudicate_three_family(
        thomas_text,
        {"claude": tr_prose, "codex": tr_prose, "gemini": tr_web},
        doc_key="thomas_split",
    )
    assert d_web.verdict == "checkeval_resolved"
    assert d_web.accepted_tuple == ("usable", "web_page", False, "hearing_transcript")

    # 2) NIH Biographical Sketch form template: prose vs table_or_form -> resolves to table_or_form.
    nih_text = (
        "BIOGRAPHICAL SKETCH\n"
        "NAME Rashid L Bashshur\n"
        "POSITION TITLE Director of Telemedicine\n"
        "EDUCATION/TRAINING American University of Beirut\n"
    )
    bio_prose = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "witness_biography",
    }
    bio_form = {**bio_prose, "media_format": "table_or_form"}
    d_form = adjudicate_three_family(
        nih_text,
        {"claude": bio_prose, "codex": bio_form, "gemini": bio_prose},
        doc_key="nih_split",
    )
    assert d_form.verdict == "checkeval_resolved"
    assert d_form.accepted_tuple == ("usable", "table_or_form", False, "witness_biography")

    # 3) Single Senate Report: is_packet=False vs True -> resolves to is_packet=False.
    srpt_text = (
        "[Senate Report 106-233]\n"
        "[From the U.S. Government Publishing Office]\n"
        "106th Congress SENATE Report 106-233\n"
        "SPANISH PEAKS WILDERNESS ACT OF 1999\n"
        "Mr. Murkowski, from the Committee on Energy and Natural Resources, submitted the following report."
    )
    rpt_single = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "committee_or_agency_report",
    }
    rpt_pkt = {**rpt_single, "is_packet": True}
    d_srpt = adjudicate_three_family(
        srpt_text,
        {"claude": rpt_single, "codex": rpt_pkt, "gemini": rpt_single},
        doc_key="srpt_split",
    )
    assert d_srpt.verdict == "checkeval_resolved"
    assert d_srpt.accepted_tuple == ("usable", "prose", False, "committee_or_agency_report")

    # 4) Unanimous non-usable status ignores unused media_format differences.
    cover_text = "[Senate Hearing 106-1] [From the U.S. Government Publishing Office] COVER PAGE"
    cov_prose = {"status": "cover_or_toc", "media_format": "prose", "is_packet": False, "primary_genre": None}
    cov_none = {"status": "cover_or_toc", "media_format": None, "is_packet": False, "primary_genre": None}
    d_cov = adjudicate_three_family(
        cover_text,
        {"claude": cov_prose, "codex": cov_none, "gemini": cov_none},
        doc_key="cover_norm",
    )
    assert d_cov.verdict == "auto_accept_gold"
    assert d_cov.accepted_tuple == ("cover_or_toc", None, False, None)


def test_claude_effort_and_model_id_wiring() -> None:
    cmd = build_claude_command({"type": "object"}, model="claude-opus-5-5", effort="medium")
    assert cmd[-4:] == ["--model", "claude-opus-5-5", "--effort", "medium"]

    assert RunnerConfig().model_id_for("claude") == "claude-sonnet-default"
    cfg = RunnerConfig(claude_model="claude-opus-5-5", claude_effort="medium")
    assert cfg.model_id_for("claude") == "claude-opus-5-5:effort=medium"


def test_claude_stream_json_and_codex_rollout_telemetry_and_usage_guard(tmp_path: Path) -> None:
    stream_lines = "\n".join(
        [
            json.dumps({"type": "system", "subtype": "init"}),
            json.dumps(
                {
                    "type": "rate_limit_event",
                    "rate_limit_info": {
                        "status": "allowed",
                        "unifiedWindows": {
                            "seven_day": {"utilization": 0.52, "status": "allowed"},
                        },
                    },
                }
            ),
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "structured_output": {"status": "usable"},
                    "modelUsage": {"claude-opus-5-5": {"costUSD": 0.0425}},
                }
            ),
        ]
    )
    env, pct, rl, cost = parse_claude_stream_json(stream_lines)
    assert env is not None and env["structured_output"] == {"status": "usable"}
    assert pct == pytest.approx(52.0)
    assert rl is not None and rl["status"] == "allowed"
    assert cost == pytest.approx(0.0425)

    # Synthetic Codex rollout JSONL
    tid = "01a209ad-9786-7b90-90a9-ed7da9fd82cf"
    from datetime import datetime
    now_local = datetime.now()
    rdir = tmp_path / "sessions" / f"{now_local.year:04d}" / f"{now_local.month:02d}" / f"{now_local.day:02d}"
    rdir.mkdir(parents=True, exist_ok=True)
    rfile = rdir / f"rollout-2026-11-23T13-31-41-{tid}.jsonl"
    rfile.write_text(
        json.dumps(
            {
                "type": "event_msg",
                "payload": {
                    "type": "token_count",
                    "rate_limits": {
                        "primary": {"used_percent": 14.5, "window_minutes": 10080},
                        "secondary": {"used_percent": 50.0, "window_minutes": 300},
                        "rate_limit_reached_type": None,
                    },
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    codex_pct, codex_rl = read_codex_rollout_rate_limits(tid, sessions_root=tmp_path / "sessions")
    assert codex_pct == pytest.approx(50.0)
    assert codex_rl is not None

    guard = UsageGuard(max_usage_pct=50.0)
    assert guard.record("claude", 49.9) is False
    assert guard.should_stop() is False
    assert guard.record("codex", codex_pct, codex_rl) is True
    assert guard.should_stop() is True
    assert "codex" in str(guard.triggered_reason)


def test_two_family_adjudication_unanimous_and_checkeval_tie_break() -> None:
    text = (
        "Committee Hearing Notice\n"
        "Committee on Energy and Commerce Hearing on AI Safety May 14, 2025.\n"
    )
    notice = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "hearing_or_markup_notice",
    }
    vote = {
        "status": "usable",
        "media_format": "prose",
        "is_packet": False,
        "primary_genre": "committee_vote_or_action",
    }
    d_unanimous = adjudicate_three_family(text, {"claude": notice, "codex": notice}, doc_key="two_ok")
    assert d_unanimous.verdict == "auto_accept_gold"

    def _arb(doc_text, questions, sides, candidates=None):
        del doc_text, sides, candidates
        return {
            "winner": "majority",
            "answers": [
                {
                    "qid": q.qid,
                    "answer": q.favors_side == "majority",
                    "evidence_quote": "Committee Hearing Notice",
                }
                for q in questions
            ],
        }

    d_tie = adjudicate_three_family(
        text,
        {"claude": notice, "codex": vote},
        doc_key="two_tie",
        check_eval_fn=_arb,
    )
    assert d_tie.verdict == "checkeval_resolved"
    assert d_tie.accepted_tuple == ("usable", "prose", False, "hearing_or_markup_notice")


def test_stripped_claude_and_codex_flags_and_home(tmp_path: Path) -> None:
    claude_cmd = build_claude_command(
        {"type": "object"},
        model="claude-opus-5-5",
        effort="low",
        system_prompt="Strict JSON.",
        stripped_prefix=True,
    )
    assert "--bare" not in claude_cmd
    assert "--strict-mcp-config" in claude_cmd
    assert "--disable-slash-commands" in claude_cmd
    ss_idx = claude_cmd.index("--setting-sources")
    assert claude_cmd[ss_idx + 1] == ""
    ag_idx = claude_cmd.index("--agents")
    assert claude_cmd[ag_idx + 1] == "{}"
    tools_idx = claude_cmd.index("--tools")
    assert claude_cmd[tools_idx + 1] == ""
    assert claude_cmd[-4:] == ["--model", "claude-opus-5-5", "--effort", "low"]

    codex_cmd = build_codex_command(
        tmp_path / "schema.json",
        tmp_path / "out.json",
        model="gpt-6.2-sol",
        reasoning_effort="low",
        stripped_prefix=True,
    )
    for cfg_val in (
        "mcp_servers={}",
        "plugins={}",
        'web_search="disabled"',
        'service_tier="default"',
        "notify=[]",
        "project_doc_max_bytes=0",
    ):
        assert cfg_val in codex_cmd
    for feat in (
        "code_mode_host",
        "shell_tool",
        "unified_exec",
        "plugins",
        "hooks",
        "skill_search",
        "memories",
        "multi_agent",
        "goals",
        "steer",
    ):
        idx = codex_cmd.index(feat)
        assert codex_cmd[idx - 1] == "--disable"

    fake_home, clean_codex_home = _prepare_stripped_codex_home(tmp_path)
    assert fake_home.is_dir() and clean_codex_home.is_dir()
    base_inst = clean_codex_home / "base_instructions.txt"
    cfg_toml = clean_codex_home / "config.toml"
    assert base_inst.is_file()
    cfg_txt = cfg_toml.read_text(encoding="utf-8")
    assert 'service_tier = "default"' in cfg_txt
    assert 'web_search = "disabled"' in cfg_txt
    assert "notify = []" in cfg_txt
    assert "mcp_servers = {}" in cfg_txt
    assert "plugins = {}" in cfg_txt
    assert "model_instructions_file =" in cfg_txt
    assert str(base_inst) in cfg_txt


def test_usage_guard_telemetry_families_and_agy_quota() -> None:
    guard = UsageGuard(max_usage_pct=50.0, require_telemetry=True, telemetry_families=("claude", "codex"))
    # Gemini emits no usage_pct on rc=0 and must NOT trip require_telemetry.
    for _ in range(4):
        assert guard.record("gemini", None, returncode=0) is False
    # rc=0 parse error quoting prose word "capacity" must NOT false-trip.
    assert guard.record("gemini", None, error="parse_error: grid capacity exceeded", returncode=0) is False
    assert guard.should_stop() is False
    # Non-zero agy RESOURCE_EXHAUSTED quota error MUST trip immediately.
    assert guard.record("gemini", None, error="RESOURCE_EXHAUSTED: quota exceeded", returncode=1) is True
    assert "gemini quota/rate-limit error" in str(guard.triggered_reason)

    strict_guard = UsageGuard(max_usage_pct=50.0, require_telemetry=True, telemetry_families=("claude", "codex"))
    assert strict_guard.record("claude", None, returncode=0) is False
    assert strict_guard.record("claude", None, returncode=0) is True
    assert "without usage_pct telemetry" in str(strict_guard.triggered_reason)


def test_resolve_adapter_routes_stripped_agy_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    import congress_docmeta.v7.factory.runners as runners_mod

    seen: list[tuple[str, dict[str, Any]]] = []

    def fake_stripped(
        prompt: str,
        *,
        system_prompt: str,
        model_id: str = "",
        timeout_s: float = 180.0,
        binary: str = "",
        agent_name: str = "docmeta-bulk-reviewer",
    ) -> AdapterOutput:
        del prompt, timeout_s, binary, agent_name
        seen.append(("stripped", {"system_prompt": system_prompt, "model_id": model_id}))
        return AdapterOutput(raw_text='{"items": []}', extracted_json_str='{"items": []}', returncode=0)

    def fake_unstripped(
        prompt: str,
        schema: dict[str, Any],
        *,
        model_id: str | None = None,
        timeout_s: float = 120.0,
        binary: str = "",
    ) -> AdapterOutput:
        del prompt, schema, timeout_s, binary
        seen.append(("unstripped", {"model_id": model_id}))
        return AdapterOutput(raw_text="{}", extracted_json_str="{}", returncode=0)

    monkeypatch.setattr(runners_mod, "invoke_agy_stripped_cli", fake_stripped)
    monkeypatch.setattr(runners_mod, "invoke_agy_cli", fake_unstripped)

    cfg_stripped = RunnerConfig(
        stripped_prefix=True,
        system_prompt="SYS",
        gemini_model="gemini-4-neon-low",
    )
    provider, adapter_fn = runners_mod._resolve_adapter("gemini", cfg_stripped, None)
    assert provider == "agy_cli"
    adapter_fn("hello", {"type": "object"}, model_id=cfg_stripped.model_id_for("gemini"), timeout_s=30.0)
    assert seen[-1] == ("stripped", {"system_prompt": "SYS", "model_id": "gemini-4-neon-low"})

    cfg_plain = RunnerConfig(stripped_prefix=False, gemini_model="gemini-4-neon-low")
    _, plain_fn = runners_mod._resolve_adapter("gemini", cfg_plain, None)
    plain_fn("hello", {"type": "object"}, model_id=cfg_plain.model_id_for("gemini"), timeout_s=30.0)
    assert seen[-1] == ("unstripped", {"model_id": "gemini-4-neon-low"})
