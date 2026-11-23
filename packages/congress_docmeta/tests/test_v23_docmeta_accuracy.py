"""Regression tests for Track A DocMeta V6.3+ accuracy, salvage, tail harvesting, and offline escalation."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import types
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_docmeta import CANONICAL_CROQ_KINDS, cli, hygiene_and_line_parsers_v6, parquet_runner_v6, pythonic_v6
from congress_docmeta.grammar_router_ane_v6 import PreDecodeGrammarRouterV6
from congress_docmeta.pythonic_v5 import (
    _salvage_truncated_docmeta_v4,
    detect_new_tier1_signatures_v5,
    detect_ttf_page_signature,
    detect_v4_tier1_signatures,
    has_structural_docmeta_corruption_v4,
    repair_clean_docmeta_budget_v4,
)
from congress_docmeta.schema_v4 import MAX_PERSONAS


class _ByteTokenizer:
    def apply_chat_template(
        self,
        msgs: list[dict[str, str]],
        *,
        tokenize: bool = False,
        add_generation_prompt: bool = True,
        enable_thinking: bool = True,
    ) -> str:
        assert enable_thinking is False
        return msgs[0]["content"]

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        return list(text.encode("utf-8"))

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
        return bytes(int(x) & 0xFF for x in ids).decode("utf-8", errors="ignore")


def _install_fake_fast_gemma4(monkeypatch: pytest.MonkeyPatch) -> None:
    fg4_pkg = types.ModuleType("fast_gemma4")
    fg4_grammar = types.ModuleType("fast_gemma4.grammar")

    class _FakeGrammarHelper:
        def __init__(self, tok: Any, schema_str: str, new_to_old: Any, whitespace_flexible: bool = False) -> None:
            self.upfront_ff: list[int] = []
            self.schema_str = schema_str

    class _FakePerDocGrammarHelper:
        def __init__(self, gh_std: Any, doc_order: Any = (), **kwargs: Any) -> None:
            self.upfront_ff: list[int] = list(getattr(gh_std, "upfront_ff", ()))
            self._cursor = 0
            self.dispatched_doc_indices: list[int] = []
            self._n = len(doc_order) if doc_order else len(kwargs.get("doc_schema_keys") or ())

        def get_grammar_entry(self, kind: str) -> None:
            return None

    fg4_grammar.GrammarHelper = _FakeGrammarHelper  # type: ignore[attr-defined]
    fg4_pdg = types.ModuleType("fast_gemma4.per_doc_grammar")
    fg4_pdg.PerDocGrammarHelper = _FakePerDocGrammarHelper  # type: ignore[attr-defined]
    fg4_pdg.compute_rolling_doc_order = lambda suf_ids, **_: list(range(len(suf_ids)))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fast_gemma4", fg4_pkg)
    monkeypatch.setitem(sys.modules, "fast_gemma4.grammar", fg4_grammar)
    monkeypatch.setitem(sys.modules, "fast_gemma4.per_doc_grammar", fg4_pdg)


def test_salvage_compact_wire_preserves_target_kind_and_clamps_25w_gist() -> None:
    # Truncated compact JSON output exceeding 25w gist and truncated before closing braces
    long_gist = " ".join(f"word{i}" for i in range(1, 33))
    raw_trunc = (
        '{"st":"usable","tq":"native","ch":"house","cg":113,'
        f'"gi":"{long_gist}","ct":"Truth in Testimony Disclosure Form","tp":["disclosure"'
    )
    salvaged = _salvage_truncated_docmeta_v4(
        raw_trunc,
        filename="HHRG-113-HM12-TTF-SpanglerK-20130919.pdf",
        wire_format="compact",
        target_primary_kind="truth_in_testimony_disclosure",
    )
    assert salvaged["status"] == "usable"
    assert salvaged["primary_kind"] == "truth_in_testimony_disclosure"
    assert len(salvaged["gist"].split()) <= 25
    assert salvaged["composed_title"] == "Truth in Testimony Disclosure Form"
    assert salvaged["topics"] == ["disclosure"]

    # Pipe-joined multi-kind spec is NOT singleton; falls back safely to "other" when pk absent
    salvaged_multi = _salvage_truncated_docmeta_v4(
        '{"st":"usable","tq":"native","ct":"Letter"',
        filename="sample.pdf",
        wire_format="compact",
        target_primary_kind="oversight_letter|external_submission_letter",
    )
    assert salvaged_multi["primary_kind"] == "other"


def test_clean_budget_repair_vs_structural_corruption_wipe(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_fast_gemma4(monkeypatch)
    monkeypatch.setenv("DOCMETA_NO_PREFLIGHT_WARN", "1")
    tok = _ByteTokenizer()

    over_gist = " ".join(f"token{i}" for i in range(1, 31))
    clean_over_budget = {
        "status": "usable",
        "text_quality": "native",
        "primary_kind": "committee_amendment",
        "composed_title": "Paul S. 558 Amendment #1",
        "gist": over_gist,
        "topics": ["healthcare", "amendments"],
    }
    corrupt_refs = {
        "status": "usable",
        "text_quality": "native",
        "primary_kind": "oversight_letter",
        "composed_title": "Corrupt Output",
        "gist": over_gist,
        "topics": ["oversight"],
        "refs": [{}],
    }
    corrupt_personas = {
        "status": "usable",
        "text_quality": "native",
        "primary_kind": "oversight_letter",
        "composed_title": "Corrupt Personas",
        "gist": "Short gist.",
        "topics": ["oversight"],
        "personas": "Jane Doe",
    }

    assert not has_structural_docmeta_corruption_v4(clean_over_budget, require_primary_kind=True)
    assert has_structural_docmeta_corruption_v4(corrupt_refs, require_primary_kind=True)
    assert has_structural_docmeta_corruption_v4(corrupt_personas, require_primary_kind=True)
    assert has_structural_docmeta_corruption_v4({"status": "usable", "gist": "x"}, require_primary_kind=True)

    repaired = repair_clean_docmeta_budget_v4(clean_over_budget, filename="Paul S. 558 Amendment #1.pdf")
    assert len(repaired["gist"].split()) <= 25

    payloads = [clean_over_budget, corrupt_refs, corrupt_personas]

    class _FakeEng:
        tokenizer = tok
        new_to_old = list(range(256))

        def run_rolling(self, **kwargs: Any) -> dict[str, Any]:
            gen_toks = [tok.encode(json.dumps(p, separators=(",", ":"))) for p in payloads[: len(kwargs["suf_ids_list"])]]
            return {
                "gen_toks": gen_toks,
                "prefill_sec": 0.01,
                "decode_sec": 0.01,
                "mask_fallbacks": 0,
                "llm_steps": len(gen_toks),
                "ff_early14_steps": 0,
            }

    rows = [
        {
            "link_key_hex": f"{i:016x}",
            "filename": fn,
            "p12_raw_text": "Amendment in the nature of a substitute offered to S. 558 in committee markup session. " * 4,
            "known_json": "{}",
            "effective_format": "pdf",
        }
        for i, fn in enumerate(
            ("Paul S. 558 Amendment #1.pdf", "bad_refs.pdf", "bad_personas.pdf")
        )
    ]
    in_pq = tmp_path / "in.parquet"
    out_pq = tmp_path / "out.parquet"
    pq.write_table(pa.Table.from_pylist(rows), in_pq)

    parquet_runner_v6.run_docmeta_parquet_sweep(
        _FakeEng(),
        in_pq,
        out_pq,
        chunk_rows=8,
        b_slots=4,
        wire_format="v4",
        grammar_router="none",
        use_ane_ring=False,
        use_extractconf=False,
    )
    out_rows = pq.read_table(out_pq).to_pylist()
    assert out_rows[0]["status"] == "usable"
    assert out_rows[0]["primary_kind"] == "committee_amendment"
    assert len(json.loads(out_rows[0]["docmeta_json"])["gist"].split()) <= 25
    assert out_rows[1]["status"] == "stub_or_blank"
    assert out_rows[2]["status"] == "stub_or_blank"


def test_tier1_transcript_ttf_prefix_and_grammar_router_lock_clearing(tmp_path: Path) -> None:
    transcript_txt = (
        "Diversified Reporting Services, Inc. RPTS\n"
        "HOUSE COMMITTEE ON ENERGY AND COMMERCE\n"
        "Markup Transcript\n"
        "February 25, 2025\n"
    )
    hits_tr = detect_new_tier1_signatures_v5("HMKP-119-IF00-Transcript-20250225.pdf", transcript_txt)
    assert [k for _, k in hits_tr] == ["hearing_transcript"]
    # V4 signature map stays completely untouched
    assert detect_v4_tier1_signatures("HMKP-119-IF00-Transcript-20250225.pdf", transcript_txt) == []

    spangler_txt = (
        "Witness Name: Kevin Spangler\n"
        "Committee on Homeland Security hearing background form\n"
        "5. Please list any federal grants or contracts (including subgrants or subcontracts) received since October 1, 2010.\n"
    )
    assert detect_ttf_page_signature(spangler_txt) is not None
    assert [
        k for _, k in detect_new_tier1_signatures_v5("HHRG-113-HM12-TTF-SpanglerK-20130919.pdf", spangler_txt)
    ] == ["truth_in_testimony_disclosure"]

    dow_txt = "\x00garbled font bytes\nNone\nNone\nDigitally signed by Robert Dow\n"
    assert [
        k for _, k in detect_new_tier1_signatures_v5("HHRG-114-HM11-TTF-DowR-20150317.pdf", dow_txt)
    ] == ["truth_in_testimony_disclosure"]

    # Non-TTF witness statement with "Digitally signed by" MUST NOT misclassify as TTF
    wstate_txt = "Statement of R. Friedman, PhD\nDigitally signed by R. Friedman\n"
    assert detect_new_tier1_signatures_v5("HHRG-115-SY00-Wstate-FriedmanPhDR-20170629.pdf", wstate_txt) == []

    # PreDecodeGrammarRouterV6 must respect cleared pmeta["tier1_target_kind"] = None even when row has stale locked_primary_kind
    import numpy as np

    art_dir = tmp_path / "router_artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    classes = list(CANONICAL_CROQ_KINDS) + ["status:stub_or_blank", "status:garbled_ocr"]
    dim = 4096
    rng = np.random.default_rng(12345)
    W = rng.normal(0.0, 0.002, size=(len(classes), dim)).astype(np.float16)
    b = np.zeros((len(classes),), dtype=np.float32)
    for st_cls in ("status:stub_or_blank", "status:garbled_ocr"):
        b[classes.index(st_cls)] = -15.0
    np.savez(
        art_dir / "router_v63_linear.npz",
        W_f16=W,
        b_f32=b,
        classes=np.asarray(classes),
        dim=np.asarray(dim, dtype=np.int32),
        temperature=np.asarray(1.0, dtype=np.float32),
    )
    (art_dir / "router_v63_calibration.json").write_text(
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
    router = PreDecodeGrammarRouterV6(mode="fast", artifacts_dir=art_dir)
    decs = router.route_chunk(
        [
            {
                "locked_primary_kind": "oversight_plan",
                "filename": "HMKP-119-IF00-Transcript-20250225.pdf",
                "p12_raw_text": "Hearing transcript text mentioning committee witnesses and Q&A.",
            }
        ],
        [{"tier1_target_kind": None, "triage": None, "zero_llm_docmeta": None}],
    )
    assert decs[0]["lock_type"] != "det_locked"
    assert decs[0]["lock_spec"] != "oversight_plan"


def test_ba00_fd00_committee_fixes_in_post_pass() -> None:
    obj_ba, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "chamber": "house",
            "congress": 119,
            "committees": ["House Committee on Banking, Housing, and Urban Affairs"],
            "primary_kind": "witness_biography",
            "composed_title": "Biography of L. Martin",
            "gist": "Witness biography submitted to House Financial Services Committee.",
            "topics": ["housing"],
        },
        known=json.dumps({"cmt": ["hsba00"]}),
        filename="HHRG-119-BA00-Bio-MartinL-20260902.pdf",
        text="L. Martin serves as Director of Policy at Housing Institute.",
        use_relational=False,
    )
    assert obj_ba["committees"] == ["House Committee on Financial Services"]

    obj_senate, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "chamber": "senate",
            "congress": 118,
            "committees": ["Senate Committee on Banking, Housing, and Urban Affairs"],
            "primary_kind": "witness_statement",
            "composed_title": "Senate Banking Testimony",
            "gist": "Testimony before the Senate Banking Committee.",
            "topics": ["banking"],
        },
        known="{}",
        filename="senate-banking-statement.pdf",
        text="Testimony before the Senate Committee on Banking, Housing, and Urban Affairs.",
        use_relational=False,
    )
    assert obj_senate["committees"] == ["Senate Committee on Banking, Housing, and Urban Affairs"]

    obj_fd, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "chamber": "house",
            "congress": 118,
            "committees": [
                "House Committee on Foreign Affairs",
                "Select Committee on Strategic Competition Between the United States and the Chinese Communist Party",
            ],
            "primary_kind": "witness_biography",
            "composed_title": "Biography of Michael Shellenberger",
            "gist": "Witness biography submitted to the Select Committee.",
            "topics": ["strategic competition"],
        },
        known=json.dumps({"cmt": ["hlfd00"]}),
        filename="HHRG-118-FD00-Bio-ShellenbergerM-20230309.pdf",
        text="Michael Shellenberger is an author and journalist testifying before the Select Committee.",
        use_relational=False,
    )
    assert "House Committee on Foreign Affairs" not in obj_fd.get("committees", [])


def test_greater_6k_tail_toc_personas_conversational_guard_and_cap() -> None:
    # 1. Conversational guard against "HURD. Good copy. Mr."
    witnesses_parsed = hygiene_and_line_parsers_v6.parse_document_witnesses(
        "Mr. HURD. Good copy. Mr. Chairman, thank you.\n"
        "WITNESSES:\n"
        "Jane Doe, Director, Clean Water Fund\n"
    )
    assert all("Good" not in w.get("name", "") for w in witnesses_parsed)

    # 1b. Memo witness harvesting preserves middle initials (W., D., E.) while rejecting job titles, orgs, and Caesar garble
    memo_res = hygiene_and_line_parsers_v6.harvest_tail_and_toc_personas_v6(
        "WITNESSES\n"
        "The following witnesses have been invited to testify:\n"
        "Panel I:\n"
        "The Honorable E. Scott Pruitt\n"
        "Administrator\n"
        "Environmental Protection Agency\n\n"
        "Panel II:\n"
        "Shaun W. Mock, CPA\n\n"
        "Chief Financial Officer\n\n"
        "Snapping Shoals Electric Membership Corporation\n"
        "Richard D. Shockey\n\n"
        "Principal\n\n"
        "Shockey Consulting\n"
        "Mr. Paraic O'Brien\n"
        "Foreign Correspondent\n"
        "Channel 4 News\n"
        "Ms. Jessica Culpepper\n"
        "Food Project Attorney\n"
        "Public Justice\n\n"
        "The Honorable Lee H. Hamilton\n"
        "Director\n"
        "The Center on Congress at The Indiana University\n"
        "Former Member, U.S. House of Representatives (D-IN)\n",
        primary_kind="hearing_memo_or_charter",
    )
    memo_names = [p["name"] for p in memo_res["tail_personas"]]
    assert "E. Scott Pruitt" in memo_names
    assert "Shaun W. Mock" in memo_names
    assert "Richard D. Shockey" in memo_names
    assert "Paraic O'Brien" in memo_names
    assert "Jessica Culpepper" in memo_names
    assert "Lee H. Hamilton" in memo_names
    for bad in ("Environmental Protection Agency", "Foreign Correspondent", "Public Justice", "Former Member"):
        assert bad not in memo_names

    garbled_res = hygiene_and_line_parsers_v6.harvest_tail_and_toc_personas_v6(
        "WITNESSES:\nWR WKe VLdeOLQeV.\n###\nUnsubscribe from this list\n",
        primary_kind="hearing_notice",
    )
    assert garbled_res["tail_personas"] == []

    # 2. GPO p3 slice parsing handles PANEL OF WITNESSES, Appendix skip, and un-dotted lines
    p3_slice = (
        "CONTENTS\n"
        "Appendix: Supplemental Submissions ...... 99\n"
        "PANEL OF WITNESSES\n"
        "H. David Kotz, Inspector General, SEC\n"
        "Leon M. Metzger, Adjunct Professor, NYU\n"
    )
    p3_res = hygiene_and_line_parsers_v6.parse_gpo_p3_slice_personas_v6(p3_slice)
    p3_names = [p["name"] for p in p3_res]
    assert "H. David Kotz" in p3_names
    assert "Leon M. Metzger" in p3_names
    assert not any("Appendix" in n for n in p3_names)

    # 3. >6k transcript merges missing witnesses, preserves existing sender role, harvests tail close
    long_body = ("Opening discussion on securities regulation. " * 200)
    transcript_full = (
        long_body
        + "\n---\nRespectfully submitted,\n"
        + "Jeanne de Cervens\n"
        + "VP and Director of Government Relations\n"
        + "Consumer Federation of America\n"
    )
    obj_tr, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "hearing_transcript",
            "personas": [{"name": "Stephen P. Harbeck", "role": "sender", "entity_type": "non_gov_person"}],
            "composed_title": "SIPC Oversight Hearing",
            "gist": "Committee oversight hearing regarding SEC and SIPC governance.",
            "topics": ["securities"],
        },
        known="{}",
        filename="111-B.pdf",
        text=transcript_full,
        multipage={"p3_toc_or_gavel_slice": p3_slice},
        use_relational=False,
    )
    by_name_tr = {p["name"]: p for p in obj_tr["personas"]}
    assert by_name_tr["Stephen P. Harbeck"]["role"] == "sender"
    assert "H. David Kotz" in by_name_tr and by_name_tr["H. David Kotz"]["role"] == "witness"
    assert "Leon M. Metzger" in by_name_tr
    assert "Jeanne de Cervens" in by_name_tr

    # 4. >6k coalition letter: org sender + signatory_count=18 + bare stopword pruning + dedup + <=10 cap
    coalition_orgs = "\n".join(f"{name}" for name in [
        "Prairie Rivers Network",
        "Clean Water Action Association",
        "Environmental Law Society",
        "Riverkeeper Alliance Group",
        "Sierra Club Chapter Council",
        "Great Lakes Basin Network",
        "Midwest Advocacy Coalition",
        "National Watershed Council",
        "Safe Drinking Water Fund",
        "Public Health Coalition",
        "Consumer Protection League",
        "Rural Community Network",
    ])
    letter_text = ("The undersigned 18 coalition groups urge support for water protections. " * 120) + "\nRespectfully,\n" + coalition_orgs
    llm_signers = [
        {"name": "John Shimkus", "role": "recipient", "entity_type": "member"},
        {"name": "Rep. John Shimkus", "role": "recipient", "entity_type": "member"},
        {"name": "President", "role": "author_or_speaker", "entity_type": "non_gov_person"},
        {"name": "Bill", "role": "author_or_speaker", "entity_type": "non_gov_person"},
    ] + [
        {"name": f"Signer Person{i}", "role": "cosigner", "entity_type": "non_gov_person"}
        for i in range(1, 14)
    ]
    obj_let, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "external_submission_letter",
            "personas": llm_signers,
            "composed_title": "Coalition Letter to Rep. Shimkus",
            "gist": "Coalition of 18 groups urging support for clean water protections.",
            "topics": ["clean water"],
        },
        known="{}",
        filename="Letter-Shimkus.pdf",
        text=letter_text,
        use_relational=False,
    )
    ps_let = obj_let["personas"]
    assert len(ps_let) <= 10
    assert obj_let["signatory_count"] == 18
    names_let = [p["name"] for p in ps_let]
    assert "President" not in names_let and "Bill" not in names_let
    assert sum(1 for n in names_let if "Shimkus" in n) == 1
    assert any(p["name"] == "Prairie Rivers Network" and p["entity_type"] == "organization" for p in ps_let)

    # 5. Hearing transcript still permits >10 personas up to MAX_PERSONAS
    many_w = [{"name": f"Witness {i} Last{i}", "role": "witness", "entity_type": "non_gov_person"} for i in range(15)]
    obj_many, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "hearing_transcript",
            "personas": many_w,
            "composed_title": "Multi-Panel Hearing",
            "gist": "Full hearing transcript with fifteen witnesses across three panels.",
            "topics": ["oversight"],
        },
        known="{}",
        filename="hearing.pdf",
        text="Hearing transcript text.",
        use_relational=False,
    )
    assert 15 == len(obj_many["personas"]) <= MAX_PERSONAS


def test_witness_biography_unprinted_date_restraint_and_recovery() -> None:
    # Unprinted leaked date from known / filename must be stripped
    bio_unprinted, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "witness_biography",
            "event_date": "2026-09-02",
            "doc_date": "2026-09-02",
            "composed_title": "Biography of L. Martin",
            "gist": "Professional biography of witness L. Martin.",
            "topics": ["housing"],
        },
        known=json.dumps({"date": "2026-09-02"}),
        filename="HHRG-119-BA00-Bio-MartinL-20260902.pdf",
        text="L. Martin has twenty years of experience in affordable housing finance.",
        use_relational=False,
    )
    assert "event_date" not in bio_unprinted
    assert "doc_date" not in bio_unprinted

    # Military "Current as of Month YYYY" recovers doc_date and strips leaked event_date
    bio_cur, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "witness_biography",
            "event_date": "2019-06-12",
            "doc_date": "2019-06-12",
            "composed_title": "Biography of Col. L. Travis",
            "gist": "Military biography of Colonel Travis.",
            "topics": ["defense"],
        },
        known=json.dumps({"date": "2019-06-12"}),
        filename="HHRG-116-AS00-Bio-TravisL-20190612.pdf",
        text="Colonel Travis commands the Air Mobility Wing.\n(Current as of July 2012)\n",
        use_relational=False,
    )
    assert "event_date" not in bio_cur
    assert bio_cur.get("doc_date") == "2012-07"

    # Standalone trailing footer "March 2023" recovers doc_date
    bio_ftr, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "witness_biography",
            "composed_title": "Biography of A. Caputo",
            "gist": "Biography of defense analyst A. Caputo.",
            "topics": ["defense"],
        },
        known="{}",
        filename="HHRG-118-AS00-Bio-CaputoA-20230418.pdf",
        text="A. Caputo specializes in industrial base policy.\n\nMarch 2023\n",
        use_relational=False,
    )
    assert bio_ftr.get("doc_date") == "2023-03"

    # Explicitly printed numeric date "2/23/2015" is preserved
    bio_num, _ = pythonic_v6.post_pass_v6(
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "witness_biography",
            "doc_date": "2015-02-23",
            "composed_title": "Biography of T. Halvorsen",
            "gist": "Biography of DOD CIO Terry Halvorsen.",
            "topics": ["cybersecurity"],
        },
        known="{}",
        filename="HHRG-114-AS00-Bio-HalvorsenT-20150225.pdf",
        text="Terry A. Halvorsen, Department of Defense CIO.\n2/23/2015\n",
        use_relational=False,
    )
    assert bio_num.get("doc_date") == "2015-02-23"


def test_async_single_model_escalation_queue_and_cli_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_fake_fast_gemma4(monkeypatch)
    monkeypatch.setenv("DOCMETA_NO_PREFLIGHT_WARN", "1")
    tok = _ByteTokenizer()

    # Row 0: flagged anomaly (ungrounded gist / mismatch); Row 1: clean row
    pass1_docs = [
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "other",
            "composed_title": "Unknown Doc",
            "gist": "Totally unrelated summary mentioning quantum submarines and lunar habitats.",
            "topics": ["unknown"],
        },
        {
            "status": "usable",
            "text_quality": "native",
            "primary_kind": "witness_statement",
            "personas": [{"name": "Jane Doe", "role": "witness", "entity_type": "non_gov_person"}],
            "composed_title": "Clean Testimony on Water Infrastructure",
            "gist": "Testimony of Jane Doe on drinking water infrastructure funding before the subcommittee.",
            "topics": ["water infrastructure"],
        },
    ]

    class _Pass1OnlyEng:
        tokenizer = tok
        new_to_old = list(range(256))

        def run_rolling(self, **kwargs: Any) -> dict[str, Any]:
            n = len(kwargs["suf_ids_list"])
            gh = kwargs.get("gh")
            if gh is not None and hasattr(gh, "_cursor"):
                gh._cursor = n
                gh.dispatched_doc_indices = list(range(n))
            return {
                "gen_toks": [tok.encode(json.dumps(pass1_docs[i], separators=(",", ":"))) for i in range(n)],
                "prefill_sec": 0.01,
                "decode_sec": 0.01,
                "mask_fallbacks": 0,
                "llm_steps": n,
                "ff_early14_steps": 0,
            }

    in_pq = tmp_path / "queue.parquet"
    p1_pq = tmp_path / "pass1.parquet"
    merged_pq = tmp_path / "merged.parquet"
    esc_jsonl = tmp_path / "escalate.jsonl"

    rows = [
        {
            "link_key_hex": "0000000000000001",
            "filename": "submission-energy.pdf",
            "p12_raw_text": (
                "Testimony of John Smith, Grid Reliability Director, submitted for the hearing record on "
                "transmission permitting reforms and bulk electric system standards. " * 3
            ),
            "known_json": "{}",
            "effective_format": "pdf",
        },
        {
            "link_key_hex": "0000000000000002",
            "filename": "clean-water.pdf",
            "p12_raw_text": (
                "Testimony of Jane Doe on drinking water infrastructure funding before the subcommittee. " * 3
            ),
            "known_json": "{}",
            "effective_format": "pdf",
        },
    ]
    pq.write_table(pa.Table.from_pylist(rows), in_pq)

    summary = parquet_runner_v6.run_docmeta_parquet_sweep(
        _Pass1OnlyEng(),
        in_pq,
        p1_pq,
        chunk_rows=8,
        b_slots=4,
        wire_format="v4",
        grammar_router="none",
        use_ane_ring=False,
        escalate_gpt_oss=False,
        escalation_queue_out=esc_jsonl,
    )
    assert summary.escalation_queue_path == esc_jsonl
    assert esc_jsonl.exists()
    q_lines = [json.loads(ln) for ln in esc_jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert any(item["link_key_hex"] == "0000000000000001" for item in q_lines)

    # Phase 2 offline single-model GPT-OSS-20B rerun over exported queue (0 Pass-1 co-residency!)
    repaired_p2 = {
        "status": "usable",
        "text_quality": "native",
        "primary_kind": "witness_statement",
        "personas": [{"name": "John Smith", "role": "witness", "entity_type": "non_gov_person"}],
        "composed_title": "Testimony of John Smith on Transmission Permitting",
        "gist": "Testimony of John Smith on transmission permitting reforms and bulk electric system standards.",
        "topics": ["grid reliability"],
    }

    class _FakeGptOssEng:
        def __init__(self) -> None:
            self.calls = 0

        def generate_batch(self, prompts: list[str], *, per_doc_grammars: Any = None, **kwargs: Any) -> Any:
            self.calls += 1
            items = [
                types.SimpleNamespace(parsed=repaired_p2, text=json.dumps(repaired_p2))
                for _ in prompts
            ]
            return types.SimpleNamespace(items=items)

    fake_p2 = _FakeGptOssEng()
    receipt = parquet_runner_v6.run_offline_escalation_queue_v6(
        esc_jsonl,
        p1_pq,
        merged_pq,
        gpt_oss_engine=fake_p2,
        use_wired_limit=False,
    )
    assert fake_p2.calls == 1
    assert receipt["queued_docs"] == len(q_lines)
    assert receipt["accepted_docs"] >= 1
    merged_rows = {r["link_key_hex"]: r for r in pq.read_table(merged_pq).to_pylist()}
    assert merged_rows["0000000000000001"]["pass2_escalated"] is True
    assert merged_rows["0000000000000001"]["docmeta_source"] == "fast-gpt-oss-20b-pass2"
    assert merged_rows["0000000000000001"]["primary_kind"] == "witness_statement"
    assert merged_rows["0000000000000001"]["pass1_docmeta_json"] is not None

    # Empty escalation queue executes cleanly without invoking Pass-2 model
    empty_q = tmp_path / "empty_escalate.jsonl"
    empty_q.write_text("", encoding="utf-8")
    empty_out = tmp_path / "empty_merged.parquet"
    receipt_empty = parquet_runner_v6.run_offline_escalation_queue_v6(
        empty_q,
        p1_pq,
        empty_out,
        use_wired_limit=False,
    )
    assert receipt_empty["queued_docs"] == 0
    assert empty_out.exists()

    # CLI flags parse cleanly while preserving all docmeta-sweep defaults
    sweep_args = cli.build_parser().parse_args(
        ["docmeta-sweep", "in.parquet", "out.parquet", "--escalation-queue-out", "q.jsonl"]
    )
    assert sweep_args.escalation_queue_out == "q.jsonl"
    assert sweep_args.retry_escalated is None
    re_args = cli.build_parser().parse_args(["retry-escalated", "q.jsonl", "p1.parquet", "out.parquet"])
    assert re_args.cmd == "retry-escalated"
    assert re_args.escalation_queue == "q.jsonl"
    assert re_args.pass1_results == "p1.parquet"
    assert re_args.output == "out.parquet"


def test_qwen_pass2_whitespace_flexible_lora_and_cli_wiring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from congress_docmeta import silicon_runtime_v6

    _install_fake_fast_gemma4(monkeypatch)

    seen_ws_gh: list[Any] = []
    fg4_grammar = sys.modules["fast_gemma4.grammar"]
    orig_gh = fg4_grammar.GrammarHelper

    class _CapturingGH(orig_gh):  # type: ignore[misc, valid-type]
        def __init__(self, tok: Any, schema_str: str, new_to_old: Any, whitespace_flexible: Any = False) -> None:
            seen_ws_gh.append(whitespace_flexible)
            super().__init__(tok, schema_str, new_to_old, whitespace_flexible=whitespace_flexible)

    monkeypatch.setattr(fg4_grammar, "GrammarHelper", _CapturingGH)

    class _FakeQwenEngine:
        def __init__(
            self,
            *,
            model_dir: Any = None,
            lora_adapter: Any = None,
            default_enable_thinking: bool = False,
            warmup: bool = True,
        ) -> None:
            self.model_dir = model_dir
            self.lora_adapter = lora_adapter
            self.default_enable_thinking = default_enable_thinking
            self.warmup = warmup
            self.tokenizer = _ByteTokenizer()
            self.model_name = "Qwen3.5-9B-OptiQ-4bit"
            self.calls: list[dict[str, Any]] = []

        def generate_batch(
            self,
            prompts: list[str],
            *,
            per_doc_grammars: Any = None,
            whitespace_flexible: bool | None = None,
            **kwargs: Any,
        ) -> Any:
            self.calls.append({"whitespace_flexible": whitespace_flexible, **kwargs})
            repaired = {
                "status": "usable",
                "text_quality": "native",
                "primary_kind": "witness_statement",
                "personas": [{"name": "John Smith", "role": "witness", "entity_type": "non_gov_person"}],
                "composed_title": "Testimony of John Smith on Transmission Permitting",
                "gist": "Testimony of John Smith on transmission permitting reforms and bulk electric system standards.",
                "topics": ["grid reliability"],
            }
            return types.SimpleNamespace(
                items=[types.SimpleNamespace(parsed=repaired, text=json.dumps(repaired)) for _ in prompts]
            )

    q_eng = _FakeQwenEngine(model_dir="9b-optiq", lora_adapter="/tmp/fake-lora")
    g_eng = types.SimpleNamespace(tokenizer=_ByteTokenizer(), model_name="gemma-4-e2b-it")
    assert silicon_runtime_v6.resolve_default_whitespace_flexible(q_eng) is None
    assert silicon_runtime_v6.resolve_default_whitespace_flexible(g_eng) is False
    assert silicon_runtime_v6.resolve_default_whitespace_flexible(q_eng, explicit=False) is False
    assert silicon_runtime_v6.resolve_pass2_source_tag(q_eng) == "fast-qwen3-pass2"
    assert silicon_runtime_v6.resolve_pass2_source_tag(g_eng) == "fast-gpt-oss-20b-pass2"

    # PythonicEngineV6 resolves spaced `: ` grammar (`None`) for Qwen and compact (`False`) for Gemma
    pythonic_v6.PythonicEngineV6(q_eng)
    pythonic_v6.PythonicEngineV6(g_eng)
    assert seen_ws_gh == [None, False]

    # Fake `fast_qwen3.FastQwen3Engine` for `run_offline_escalation_queue_v6(escalate_qwen=True, ...)`
    created_qwen: list[_FakeQwenEngine] = []

    def _ctor(**kw: Any) -> _FakeQwenEngine:
        inst = _FakeQwenEngine(**kw)
        created_qwen.append(inst)
        return inst

    fq3_mod = types.ModuleType("fast_qwen3")
    fq3_mod.FastQwen3Engine = _ctor  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fast_qwen3", fq3_mod)

    esc_jsonl = tmp_path / "esc.jsonl"
    esc_jsonl.write_text(
        json.dumps(
            {
                "link_key_hex": "0000000000000001",
                "filename": "Wstate-SmithJ-20250201.pdf",
                "known_json": "{}",
                "p12_raw_text": "Statement of John Smith on transmission permitting standards.",
                "pass1_docmeta_json": "{}",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    p1_pq = tmp_path / "pass1.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "list_row": 0,
                    "link_key_hex": "0000000000000001",
                    "doc_key": "doc-1",
                    "package_id": None,
                    "disposition": "llm_queue",
                    "v6_route": "llm_open_extraction",
                    "docmeta_source": "fast-gemma4-e2b-v6_2",
                    "filename": "Wstate-SmithJ-20250201.pdf",
                    "effective_format": "pdf",
                    "primary_kind": "other",
                    "status": "usable",
                    "congress": 119,
                    "chamber": "house",
                    "committees": [],
                    "docmeta_json": "{}",
                    "strict_v4_valid": False,
                    "completion_tokens": 32,
                    "llm_vs_det_diff_json": "{}",
                    "anomaly_score": 1.0,
                    "anomaly_flags": ["atomic_kind_suspect"],
                    "needs_teacher_escalation": True,
                    "gist_grounding_score": 0.5,
                    "external_verifier_json": None,
                    "croq_lock_spec": None,
                    "croq_lock_type": None,
                    "extractconf_risk_json": None,
                    "pass2_escalated": False,
                    "pass1_docmeta_json": None,
                }
            ]
        ),
        p1_pq,
    )
    merged_pq = tmp_path / "merged_qwen.parquet"
    receipt = parquet_runner_v6.run_offline_escalation_queue_v6(
        esc_jsonl,
        p1_pq,
        merged_pq,
        escalate_qwen=True,
        qwen_model_dir="9b-optiq",
        qwen_lora="/tmp/test-qwen-lora",
        use_wired_limit=False,
    )
    assert len(created_qwen) == 1
    assert created_qwen[0].model_dir == "9b-optiq"
    assert created_qwen[0].lora_adapter == "/tmp/test-qwen-lora"
    assert created_qwen[0].default_enable_thinking is False
    assert created_qwen[0].calls[0]["whitespace_flexible"] is None
    assert receipt["accepted_docs"] >= 1
    out_rows = pq.read_table(merged_pq).to_pylist()
    assert out_rows[0]["docmeta_source"] == "fast-qwen3-pass2"
    assert out_rows[0]["pass2_escalated"] is True

    sweep_args = cli.build_parser().parse_args(
        ["docmeta-sweep", "in.parquet", "out.parquet", "--escalate-qwen", "--qwen-model-dir", "9b-optiq", "--qwen-lora", "/tmp/l"]
    )
    assert sweep_args.escalate_qwen is True
    assert sweep_args.qwen_model_dir == "9b-optiq"
    assert sweep_args.qwen_lora == "/tmp/l"
    re_q = cli.build_parser().parse_args(
        ["retry-escalated", "q.jsonl", "p1.parquet", "out.parquet", "--escalate-qwen", "--qwen-model-dir", "4b-optiq", "--qwen-lora", "/tmp/l2"]
    )
    assert re_q.escalate_qwen is True
    assert re_q.qwen_model_dir == "4b-optiq"
    assert re_q.qwen_lora == "/tmp/l2"
