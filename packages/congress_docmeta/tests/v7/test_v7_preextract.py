"""Unit & parity tests for `congress_docmeta.v7.preextract` (`ct-f2ai`)."""

from __future__ import annotations

from pathlib import Path

from congress_docmeta.v7 import DocStatus
from congress_docmeta.v7.preextract import (
    PreExtractResult,
    build_v7_text_window,
    detect_non_usable_status,
    extract_deterministic_signals,
)
from congress_docmeta.v7.release_contract import DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC
from viewer_publication.body_text_slices import DOCMETA_V7_WINDOW_SPEC, docmeta_v7_window


def test_detect_non_usable_status_and_negative_controls() -> None:
    assert detect_non_usable_status("   \n\t   ") == (DocStatus.stub_or_blank, "empty_or_sub_20_non_ws")
    assert detect_non_usable_status("<?xml version='1.0'?><mods><titleInfo>Hearing</titleInfo></mods>", effective_format="xml")[0] == DocStatus.catalog_xml
    assert detect_non_usable_status("403 Forbidden - Attention Required! | Cloudflare Enable JavaScript and cookies to continue")[0] == DocStatus.error_or_block
    assert detect_non_usable_status("GovInfo | U.S. Government Publishing Office\nPDF details and metadata\nAuthenticate this official document with the seal.")[0] == DocStatus.govinfo_wrapper

    # Substantive hearing discussing "404 errors", "Cloudflare", or "XML feeds" MUST NOT be misclassified.
    hearing_txt = (
        "HEARING ON CYBERSECURITY AND FEDERAL WEB MODERNIZATION\n"
        "BEFORE THE COMMITTEE ON OVERSIGHT AND ACCOUNTABILITY, 119th Congress\n"
        "The witness noted that agencies fixed 404 Not Found errors, migrated off legacy XML schemas, "
        "and deployed Cloudflare security mitigations across public portals. " * 20
    )
    assert detect_non_usable_status(hearing_txt, effective_format="pdf") == (None, None)


def test_extract_deterministic_signals_citations_dates_errata_and_stub_tail() -> None:
    sample = (
        "[ERRATA]\n"
        "S. Hrg. 117-617 — HHRG-119-IF00-Wstate-DoeJ-20250318\n"
        "ONE HUNDRED NINETEENTH CONGRESS\n"
        "Consideration of H.R. 1234, S. 567, H.J.Res. 42, Pub. L. 117-58, "
        "42 U.S.C. 1983, 17 C.F.R. 240.10b-5, and Executive Order 14112.\n"
        "Hearing Date: February 23, 2025 (2025-02-23).\n"
    )
    res = extract_deterministic_signals(sample)
    assert isinstance(res, PreExtractResult)
    assert res.deterministic_status is None
    assert res.is_gpo_errata_slip is True
    assert res.is_blank_or_stub_head_tail is False
    assert res.congress_hint == 119
    assert res.bill_refs == ("H.R. 1234", "S. 567", "H.J.Res. 42")
    assert res.public_laws == ("Pub. L. 117-58",)
    assert res.usc_refs == ("42 U.S.C. 1983",)
    assert res.cfr_refs == ("17 C.F.R. 240.10b-5",)
    assert res.executive_orders == ("E.O. 14112",)
    assert "S. Hrg. 117-617" in res.gpo_serials
    assert "HHRG-119-IF00-Wstate-DoeJ-20250318" in res.hhrg_tokens
    assert "2025-02-23" in res.date_hints
    d = res.to_dict()
    assert isinstance(d["bill_refs"], list)

    stub_tail = extract_deterministic_signals("WELFARE REFORM PROPOSALS\n\n\n[... page 390 tail ...]\n382\nFrom: public@example.org")
    assert stub_tail.is_blank_or_stub_head_tail is True


def test_build_v7_text_window_1to1_parity_with_release_contract_and_optional_rescue_parquet() -> None:
    pages = [
        "\u202dU.S. GOVERNMENT PUBLISHING OFFICE\u202c\nCommittee on Energy and Commerce",
        "Roster Page 2",
        "The Committee met at 10:00 a.m. in Room 2123 Rayburn House Office Building.",
        "Closing remarks Page 4.",
    ]
    joined = "\n".join(pages)
    offs = []
    pos = 0
    for p in pages:
        offs.append(pos)
        pos += len((p + "\n").encode("utf-8"))

    w_cm = build_v7_text_window(joined, offs)
    w_vp = docmeta_v7_window(joined, offs)
    assert w_cm == w_vp
    assert w_cm["text_window_spec"] == DOCMETA_V7_WINDOW_SPEC == DOCMETA_V7_STUDENT_TEXT_WINDOW_SPEC
    assert w_cm["p3_rescued"] is True

    rescue_pq = Path(".cache/archive-release/docmeta-v7-ocr-rescue/rescued_p15.parquet")
    if rescue_pq.is_file():
        import pyarrow.parquet as pq

        tbl = pq.read_table(rescue_pq, columns=["saved_body", "rescued_status", "rescued_text"])
        first_ok = next(r for r in tbl.to_pylist() if r["rescued_status"] == "ok" and r["rescued_text"])
        w_ov = build_v7_text_window(
            None,
            rescued_status=first_ok["rescued_status"],
            rescued_text=first_ok["rescued_text"],
        )
        assert w_ov["window_source"] == "ocr_rescue_p15"
        assert len(w_ov["text"]) <= 9000
