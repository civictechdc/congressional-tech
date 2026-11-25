"""Tests for the singular `body_text` SSOT reader (`body_text_ssot`) and `corpus_quality` SSOT integration."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.lake import body_text
from congress_api.parsers.body_text import page_offsets as compute_page_offsets
from docspec_client.client import NativeDatasets
from viewer_publication import body_text_export as export
from viewer_publication.body_text_slices import (
    DOCMETA_V7_WINDOW_MAX_CHARS,
    DOCMETA_V7_WINDOW_SPEC,
    docmeta_v7_window,
)
from viewer_publication.body_text_ssot import (
    BodyTextSSOT,
    head_tail_window,
    slice_pages,
    split_pages_utf8,
    verify_ssot_export,
)
from viewer_publication.corpus_quality.core import load_corpus_rows

VERSIONS = body_text.current_versions()


def _sha(label: str) -> bytes:
    return sha256(label.encode("utf-8")).digest()


def test_utf8_multibyte_page_slicing_and_truncated_export_safety():
    pages = [
        "Page 1: Café — résumé ✓ 𝄞 opening testimony.",
        "Page 2: Español — naïve — €500,000 budget table.",
        "Page 3: Concluding Q&A and appendix.",
        "Page 4: Sincerely,\nJane Doe, Chairwoman\nJohn Smith, Ranking Member",
    ]
    joined = "\n".join(pages)
    offsets = compute_page_offsets(pages)

    # Confirm byte offsets strictly exceed Python char offsets due to multi-byte UTF-8 codepoints
    assert offsets[1] > len(pages[0]) + 1
    assert split_pages_utf8(joined, offsets) == pages
    assert slice_pages(joined, offsets, start_page=0, max_pages=2) == "\n".join(pages[:2])
    assert slice_pages(joined, offsets, start_page=1, max_pages=2) == "\n".join(pages[1:3])
    assert slice_pages(joined, offsets, start_page=3, max_pages=1) == pages[3]
    assert slice_pages(joined, offsets, start_page=10, max_pages=1) == ""

    # Simulate an export row truncated mid-page-2 while retaining the lake's 4-page `page_offsets`
    cut_text = joined[:70]
    cut_pages = split_pages_utf8(cut_text, offsets)
    assert len(cut_pages) == 2
    assert cut_pages[0] == pages[0]
    assert slice_pages(cut_text, offsets, start_page=2, max_pages=2) == ""


def test_head_tail_window_preserves_long_html_tail_and_multipage_pdf_signers():
    # 1. Single-page >8,000-char HTML
    long_html = (
        "MASTHEAD: Senate Committee on Finance Hearing\n"
        + ("Substantive middle witness statement paragraph. " * 250)
        + "\nTAIL SIGNERS: Submitted by Senator Ron Wyden and Senator Mike Crapo, May 14, 2024."
    )
    assert len(long_html) > 10_000
    win_html = head_tail_window(long_html, [0], max_chars=8000, tail_chars=2400)
    assert len(win_html) <= 8000
    assert "MASTHEAD: Senate Committee on Finance Hearing" in win_html
    assert "TAIL SIGNERS: Submitted by Senator Ron Wyden and Senator Mike Crapo" in win_html

    # 2. Multi-page PDF (5 pages) with signers on page 5
    pdf_pages = [
        "PAGE 1 LETTERHEAD: Congress of the United States, Washington, DC 20515",
        "PAGE 2 BODY: Dear Administrator, we write regarding regional grid reliability.",
        "PAGE 3 BODY: Detailed statutory analysis " + ("alpha beta gamma " * 200),
        "PAGE 4 BODY: Additional technical citations " + ("delta epsilon " * 200),
        "PAGE 5 SIGNATURES:\nSincerely,\nRep. Cathy McMorris Rodgers\nRep. Frank Pallone, Jr.",
    ]
    joined_pdf = "\n".join(pdf_pages)
    offs_pdf = compute_page_offsets(pdf_pages)
    win_pdf = head_tail_window(joined_pdf, offs_pdf, max_chars=8000, head_pages=2, tail_chars=2400)
    assert len(win_pdf) <= 8000
    assert "PAGE 1 LETTERHEAD" in win_pdf
    assert "PAGE 2 BODY" in win_pdf
    assert "PAGE 3 BODY" not in win_pdf
    assert "[... page 5 tail ...]" in win_pdf
    assert "Rep. Cathy McMorris Rodgers" in win_pdf
    assert "Rep. Frank Pallone, Jr." in win_pdf


def test_ssot_reader_row_group_pruning_integrity_and_corpus_quality_wiring(tmp_path: Path):
    # Build 300 bodies (> 1 row group of 256 rows) including a multi-page PDF and >8k HTML
    bt_rows = []
    detail_rows = []
    for i in range(300):
        name = f"doc-{i:04d}"
        sb = _sha(name)
        lk = _sha(f"lk-{i:04d}")[:16]
        if i == 5:
            pages = [
                "Page 1 Opening Letterhead — Café",
                "Page 2 Core Request Body",
                "Page 3 Middle filler " + ("word " * 800),
                "Page 4 Final Signer: Senator Maria Cantwell",
            ]
            txt = "\n".join(pages)
            offs = list(compute_page_offsets(pages))
            parser = "pdf_text"
            fmt = "pdf"
            fn = "letter-cantwell.pdf"
        elif i == 280:
            txt = (
                "Committee Press Release Header\n"
                + ("Body paragraph text on energy policy. " * 260)
                + "\nFooter Attribution: House Committee on Science, Space, and Technology"
            )
            offs = [0]
            parser = "html_text"
            fmt = "html"
            fn = "press-release.html"
        else:
            txt = f"Short document text number {i}."
            offs = [0]
            parser = "html_text"
            fmt = "html"
            fn = f"item-{i:04d}.html"

        bt_rows.append(
            {
                "body_sha": sb,
                "parser": parser,
                "parser_version": VERSIONS[parser],
                "text": txt,
                "page_offsets": offs,
                "ocr_pages": [],
                "text_sha256": sha256(txt.encode("utf-8")).digest(),
                "macos_build": None,
            }
        )
        detail_rows.append(
            {
                "link_key": lk,
                "saved_body": sb,
                "filename": fn,
                "title": f"Title {i}",
                "format": fmt,
                "congress": 118,
                "chambers": ["senate" if i == 5 else "house"],
                "committee_keys": ["sscm00" if i == 5 else "hssy00"],
                "document_date": "2024-05-10",
                "document_kind": ["letter" if i == 5 else "press_release"],
                "document_family": ["correspondence" if i == 5 else "statement"],
            }
        )

    bt_pq = tmp_path / "body-text.parquet"
    pq.write_table(
        pa.Table.from_pylist(sorted(bt_rows, key=lambda r: r["body_sha"]), schema=body_text._text_schema()),
        bt_pq,
    )
    tables_dir = tmp_path / "published"
    tables_dir.mkdir()
    detail_pq = tables_dir / "detail.parquet"
    pq.write_table(
        pa.table(
            {
                "link_key": pa.array([r["link_key"] for r in detail_rows], pa.binary(16)),
                "saved_body": pa.array([r["saved_body"] for r in detail_rows], pa.binary(32)),
                "filename": [r["filename"] for r in detail_rows],
                "title": [r["title"] for r in detail_rows],
                "format": [r["format"] for r in detail_rows],
                "congress": [r["congress"] for r in detail_rows],
                "chambers": [r["chambers"] for r in detail_rows],
                "committee_keys": [r["committee_keys"] for r in detail_rows],
                "document_date": [r["document_date"] for r in detail_rows],
                "document_kind": [r["document_kind"] for r in detail_rows],
                "document_family": [r["document_family"] for r in detail_rows],
            }
        ),
        detail_pq,
    )

    engine = NativeDatasets.from_config(os.environ["DOCSPEC_JOB_CONFIG"])
    export_dir = tmp_path / "ssot_export"
    ptr = export.export(
        engine=engine,
        work=export_dir,
        body_text=bt_pq,
        detail=detail_pq,
        versions=VERSIONS,
    )
    assert ptr["rows"] == 300

    # Verify SSOT pointer & Parquet structure
    vinfo = verify_ssot_export(export_dir, require_pointer=True, verify_file_sha256=True)
    assert vinfo["rows"] == 300 and vinfo["num_row_groups"] == 2

    ssot = BodyTextSSOT(export_dir, require_pointer=True, verify_file_sha256=True)
    rec_map = ssot.get_many([_sha("doc-0005"), _sha("doc-0280").hex(), _sha("nonexistent")])
    assert set(rec_map) == {_sha("doc-0005"), _sha("doc-0280")}
    assert "Senator Maria Cantwell" in rec_map[_sha("doc-0005")].head_tail_window(max_chars=8000)

    # Stream SereneDB & DocMeta windows
    serene_docs = list(ssot.iter_serenedb_documents(detail_pq, limit=10))
    assert len(serene_docs) == 10
    assert serene_docs[5]["declared_page_count"] == 4

    dm_wins = list(ssot.iter_docmeta_windows(detail_pq, limit=10))
    assert "Senator Maria Cantwell" in dm_wins[5]["p12_text"]
    assert len(dm_wins[5]["p12_text"]) <= DOCMETA_V7_WINDOW_MAX_CHARS
    assert dm_wins[5]["text_window_spec"] == DOCMETA_V7_WINDOW_SPEC
    assert dm_wins[5]["window_source"] == "body_text_ssot"
    assert len(dm_wins[5]["text_window_sha256"]) == 64

    # Wire into corpus_quality.core.load_corpus_rows via body_text_ssot=export_dir
    cq_rows = load_corpus_rows(tables_dir, body_text_ssot=export_dir)
    assert len(cq_rows) == 300
    assert cq_rows[5].text_source == "body_text_ssot"
    assert "Page 1 Opening Letterhead" in cq_rows[5].p12_text
    assert "Senator Maria Cantwell" in cq_rows[5].p12_text
    assert "House Committee on Science, Space, and Technology" in cq_rows[280].p12_text
    assert len(cq_rows[280].p12_text) <= 8000

    # Tampered pointer must fail verify_ssot_export
    bad_dir = tmp_path / "bad_export"
    bad_dir.mkdir()
    (bad_dir / "export.parquet").write_bytes((export_dir / "export.parquet").read_bytes())
    (bad_dir / "current.json").write_text(json.dumps({**ptr, "rows": 299}))
    with pytest.raises(ValueError, match="row count mismatch"):
        verify_ssot_export(bad_dir)


def test_docmeta_v7_window_bidi_p3_rescue_stub_guard_and_ocr_overlay(tmp_path: Path):
    # 1. Bidi control chars stripped cleanly on single & multi-page windows.
    bidi_pages = [
        "\u202dWritten Testimony of Dr. Jayesh K. Gupta\u202c\nCommittee on Science",
        "U.S. Government Publishing Office cover note",
        "The subcommittee met at 10:00 a.m. in Room 2318 Rayburn House Office Building to consider AI weather forecasting.",
        "Page 4 tail signature: Submitted July 16, 2025.",
    ]
    joined_bidi = "\n".join(bidi_pages)
    offs_bidi = compute_page_offsets(bidi_pages)
    win = docmeta_v7_window(joined_bidi, offs_bidi)
    assert win["text_window_spec"] == DOCMETA_V7_WINDOW_SPEC
    assert win["p3_rescued"] is True
    assert "\u202d" not in win["text"] and "\u202c" not in win["text"]
    assert "[... p3 rescue ...]" in win["text"]
    assert "The subcommittee met at 10:00 a.m." in win["text"]
    assert "[... page 4 tail ...]" in win["text"]
    assert len(win["text"]) <= DOCMETA_V7_WINDOW_MAX_CHARS

    # 2. Large p12 (>6400 chars cover/roster) still preserves [... p3 rescue ...] inside 9000 chars.
    big_cover_p1 = "U.S. GOVERNMENT PUBLISHING OFFICE HEARING ON ENERGY\n" + ("MEMBER ROSTER ENTRY LINE. " * 290)
    assert len(big_cover_p1) > 7000
    cov_pages = [
        big_cover_p1,
        "Roster continuation",
        "The Committee met, pursuant to call, at 10:05 a.m., Hon. Smith presiding.",
        "Closing adjournment page 4.",
    ]
    win_big = docmeta_v7_window("\n".join(cov_pages), compute_page_offsets(cov_pages))
    assert win_big["p3_rescued"] is True
    assert "[... p3 rescue ...]" in win_big["text"]
    assert "Hon. Smith presiding" in win_big["text"]
    assert len(win_big["text"]) <= DOCMETA_V7_WINDOW_MAX_CHARS

    # 3. Blank/stub-head multi-page doc (<80 non-ws chars in head) MUST NOT emit a tail-only fragment!
    stub_pages = [
        "WELFARE REFORM PROPOSALS",
        "",
        "   ",
        "From: public_commenter@example.org\nI urge the committee to reject this proposal.",
    ]
    win_stub = docmeta_v7_window("\n".join(stub_pages), compute_page_offsets(stub_pages))
    assert "[... page 4 tail ...]" not in win_stub["text"]

    # 4. End-to-end BodyTextSSOT.iter_docmeta_windows with ocr_rescue_parquet overlay
    #    upgrades an unreadable/missing row (text=None -> ocr_rescue_p15) while NEVER bypassing `held`.
    sb_missing = _sha("missing-ocr")
    sb_held = _sha("held-ocr")
    sb_avail = _sha("avail-doc")

    export_pq = tmp_path / "export.parquet"
    avail_pages = ["\u202dOpening Statement of Chairman\u202c", "Full hearing body text " * 20]
    avail_txt = "\n".join(avail_pages)
    avail_offs = compute_page_offsets(avail_pages)
    avail_sha = sha256(avail_txt.encode("utf-8")).digest()
    pq.write_table(
        pa.table(
            {
                "saved_body": pa.array([sb_avail], type=pa.binary(32)),
                "text": pa.array([avail_txt], type=pa.string()),
                "page_offsets": pa.array([avail_offs], type=pa.list_(pa.int32())),
                "text_sha256": pa.array([avail_sha], type=pa.binary(32)),
            }
        ),
        export_pq,
    )
    from viewer_publication.body_text_ssot import footer_sha256

    ptr = {
        "rows": 1,
        "bytes": export_pq.stat().st_size,
        "sha256": sha256(export_pq.read_bytes()).hexdigest(),
        "footer_sha256": footer_sha256(export_pq),
        "release_id": "rel-test",
    }
    detail_pq = tmp_path / "detail.parquet"
    pq.write_table(
        pa.table(
            {
                "link_key": pa.array([b"\x00" * 7 + b"\x01", b"\x00" * 7 + b"\x02", b"\x00" * 7 + b"\x03"], type=pa.binary(8)),
                "saved_body": pa.array([sb_avail, sb_missing, sb_held], type=pa.binary(32)),
                "filename": ["avail.pdf", "ocr_unreadable.pdf", "held.pdf"],
                "title": ["Avail", "Missing", "Held"],
                "format": ["pdf", "pdf", "pdf"],
                "congress": [119, 119, 119],
                "chambers": [["house"], ["senate"], ["house"]],
                "committee_keys": [["hsif00"], ["ssra00"], ["hsju00"]],
                "document_date": ["2026-03-01", "2026-03-02", "2026-03-03"],
            }
        ),
        detail_pq,
    )
    coverage_pq = tmp_path / "coverage.parquet"
    pq.write_table(
        pa.table(
            {
                "body_sha256": [sb_avail.hex(), sb_missing.hex(), sb_held.hex()],
                "text_status": ["available", "missing", "held"],
                "text_sha256": pa.array([avail_sha.hex(), None, None], type=pa.string()),
            }
        ),
        coverage_pq,
    )
    ptr["detail"] = {"path": str(detail_pq), "size": detail_pq.stat().st_size, "sha256": sha256(detail_pq.read_bytes()).hexdigest()}
    ptr_path = tmp_path / "current.json"
    ptr_path.write_text(json.dumps(ptr))
    handoff_path = tmp_path / "handoff.json"
    handoff_path.write_text(
        json.dumps(
            {
                "version": 1,
                "release_id": "rel-handoff",
                "source_release_id": "rel-test",
                "export_sha256": ptr["sha256"],
                "export_pointer": {"path": str(ptr_path), "size": ptr_path.stat().st_size, "sha256": sha256(ptr_path.read_bytes()).hexdigest()},
                "detail": ptr["detail"],
                "coverage": {"path": str(coverage_pq), "size": coverage_pq.stat().st_size, "sha256": sha256(coverage_pq.read_bytes()).hexdigest()},
            }
        )
    )
    rescue_pq = tmp_path / "rescued_p15.parquet"
    pq.write_table(
        pa.table(
            {
                "saved_body": pa.array([sb_missing, sb_held], type=pa.binary(32)),
                "rescued_status": ["ok", "ok"],
                "rescued_text": ["--- Page 1 ---\nS. HRG. 116-135 NOMINATION HEARING FOR DIRECTOR OF GPO", "SHOULD NOT LEAK HELD"],
            }
        ),
        rescue_pq,
    )

    ssot = BodyTextSSOT(tmp_path, require_pointer=True, verify_file_sha256=False)
    # Test rescue helper + window producer with verify_row_hashes=True on available row
    by_fn = {
        r["filename"]: r
        for r in ssot.iter_docmeta_windows(detail_pq, handoff=handoff_path, ocr_rescue_parquet=rescue_pq)
    }
    assert by_fn["avail.pdf"]["window_source"] == "body_text_ssot"
    assert "\u202d" not in by_fn["avail.pdf"]["p12_text"]
    assert by_fn["ocr_unreadable.pdf"]["window_source"] == "ocr_rescue_p15"
    assert "NOMINATION HEARING FOR DIRECTOR OF GPO" in by_fn["ocr_unreadable.pdf"]["p12_text"]
    # Explicit held publication policy MUST NOT be bypassed by OCR overlay
    assert by_fn["held.pdf"]["window_source"] == "missing"
    assert by_fn["held.pdf"]["p12_text"] is None
