"""Tests for opt-in PDF recovery & spacing helpers (`pdf_opt_in`)."""
from __future__ import annotations

import pymupdf
import pytest
from spicy_docs.extraction.model import ExtractionError

from congress_api.parsers import body_text
from congress_api.parsers.pdf_opt_in import (
    OptInPdfReader,
    TesseractBackend,
    native_inhibit_spaces_only,
    tesseract_300dpi,
    tesseract_bounded_200dpi,
)


def _make_scanned_pdf(text_lines: list[str], *, width_pt: float = 612, height_pt: float = 792, raster_dpi: int = 150) -> bytes:
    """Create a pure image-only PDF with zero native text layer."""
    src = pymupdf.open()
    pg = src.new_page(width=width_pt, height=height_pt)
    y = 90
    for line in text_lines:
        pg.insert_text((60, y), line, fontsize=16, fontname="helv")
        y += 30
    pix = pg.get_pixmap(dpi=raster_dpi, colorspace=pymupdf.csRGB, alpha=False)
    png_bytes = pix.tobytes("png")
    src.close()

    img_doc = pymupdf.open()
    ipg = img_doc.new_page(width=width_pt, height=height_pt)
    ipg.insert_image(pymupdf.Rect(0, 0, width_pt, height_pt), stream=png_bytes)
    out = img_doc.tobytes()
    img_doc.close()
    return out


def test_tesseract_backend_identity_and_selective_scan_ocr():
    tess = TesseractBackend(language="eng", model="fast", page_segmentation_mode=3)
    try:
        ident = tess.require_reproducible_identity()
        assert ident["version"] == "5.5.4"
        assert ident["model_file"]["sha256"] == "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"
    finally:
        tess.close()

    pdf_bytes = _make_scanned_pdf(
        [
            "COMMITTEE ON ENERGY AND COMMERCE",
            "Statement of Jane Doe on Clean Drinking Water Standards",
            "Submitted for the Hearing Record on March 18, 2024.",
        ]
    )
    rule = tesseract_300dpi()
    assert rule.checkpoint_identity['backend_implementation'] == 'spicy-docs-0.85.0+ctmain.20261118'
    reading = body_text.pdf_text(pdf_bytes, strategy=rule, page_deadline_seconds=30)
    assert reading.status == "completed"
    assert reading.ocr_pages == (1,)
    assert "COMMITTEE ON ENERGY AND COMMERCE" in reading.text.upper()
    assert "Clean Drinking Water" in reading.text


def test_adaptive_max_pixels_reads_oversized_page_box_without_exceeding_pixel_ceiling():
    # A 3600 x 4680 pt page (50 x 65 inches!) would be 130,000,000 pixels at 200 DPI (> 20M limit),
    # but adaptive_max_pixels scales the integer render DPI cleanly so OCR succeeds within bounds.
    src = pymupdf.open()
    pg = src.new_page(width=3600, height=4680)
    pg.insert_text((300, 600), "OVERSIZED SCAN FORM DISCLOSURE STATEMENT", fontsize=96, fontname="helv")
    pg.insert_text((300, 820), "Witness Truth in Testimony Certification Form", fontsize=84, fontname="helv")
    pix = pg.get_pixmap(dpi=36, colorspace=pymupdf.csRGB, alpha=False)
    png_bytes = pix.tobytes("png")
    src.close()

    img_doc = pymupdf.open()
    ipg = img_doc.new_page(width=3600, height=4680)
    ipg.insert_image(pymupdf.Rect(0, 0, 3600, 4680), stream=png_bytes)
    oversized_pdf = img_doc.tobytes()
    img_doc.close()

    reading = body_text.pdf_text(oversized_pdf, strategy=tesseract_bounded_200dpi(), page_deadline_seconds=30)
    assert reading.status == "completed"
    assert reading.ocr_pages == (1,)
    assert "DISCLOSURE" in reading.text.upper()


@pytest.mark.parametrize("adaptive", [False, True])
def test_oversized_page_refuses_before_pixmap_allocation(adaptive):
    from congress_api.parsers.pdf_opt_in import _OptInPDFPage

    class Page:
        rect = pymupdf.Rect(0, 0, 10_000, 10_000)
        cropbox = mediabox = rect
        rotation = 0

        def get_pixmap(self, **kwargs):
            pytest.fail("oversized raster must not be allocated")

    reader = OptInPdfReader(dpi=200, max_pixels=20_000_000, adaptive_max_pixels=adaptive)
    with pytest.raises(ExtractionError, match="max_pixels"):
        _OptInPDFPage(Page(), 1, reader, {}).render()

    # Exercise real PyMuPDF geometry without allocating its oversized raster.
    document = pymupdf.open()
    document.new_page(width=10_000, height=10_000)
    try:
        with reader.open(document.tobytes(), "application/pdf") as opened:
            with pytest.raises(ExtractionError, match="max_pixels"):
                opened.page(1).render()
    finally:
        document.close()


def test_native_inhibit_spaces_opt_in_rule_preserves_native_prose():
    from spicy_docs.extraction.pages import _PDFPage
    from congress_api.parsers.pdf_opt_in import _OptInPDFPage

    # CT delegates native_inhibit_spaces directly to spicy-docs PR 32 (_PDFPage.native).
    assert "native" not in _OptInPDFPage.__dict__
    assert _OptInPDFPage.native is _PDFPage.native
    with pytest.raises(TypeError, match="boolean"):
        OptInPdfReader(native_inhibit_spaces="yes")  # type: ignore[arg-type]

    # Build a PDF with PDF character-spacing (`3 Tc`) where PyMuPDF infers spaces unless TEXT_INHIBIT_SPACES is set.
    tracked_doc = pymupdf.open()
    tracked_pg = tracked_doc.new_page()
    tracked_pg.insert_text((72, 100), "OF THE COMMITTEE", fontsize=12)
    tracked_pg.insert_text(
        (72, 140),
        "Subcommittee on Courts, Intellectual Property, and the Internet Hearing Notice.",
        fontsize=12,
    )
    xref = tracked_pg.get_contents()[0]
    stream = tracked_doc.xref_stream(xref)
    tracked_doc.update_stream(xref, stream.replace(b"BT", b"BT\n3 Tc", 1))
    pdf_bytes = tracked_doc.tobytes()
    tracked_doc.close()

    default_reader = OptInPdfReader(native_inhibit_spaces=False)
    with default_reader.open(pdf_bytes, "application/pdf") as opened_default:
        default_nat = opened_default.page(1).native()
        assert "O F T H E C O M M I T T E E" in default_nat.text
        assert "inhibit_spaces" not in default_nat.configuration

    reader = OptInPdfReader(native_inhibit_spaces=True)
    with reader.open(pdf_bytes, "application/pdf") as opened:
        assert opened.page_count == 1
        inhibited_nat = opened.page(1).native()
        assert inhibited_nat.configuration["inhibit_spaces"] is True
        assert "OF THE COMMITTEE" in inhibited_nat.text
    reading = body_text.pdf_text(pdf_bytes, strategy=native_inhibit_spaces_only(), page_deadline_seconds=15)
    assert reading.status == "completed"
    assert reading.ocr_pages == ()
    assert "OF THE COMMITTEE" in reading.text
    assert "Intellectual Property" in reading.text


def test_shared_wayback_readers_and_error_page_pdf_guard_import_and_validate_offline():
    import json
    from spicy_docs.reading.error_pages import detect_error_page
    from spicy_docs.sources.web_archive import (
        WaybackCdxScope,
        WaybackFallback,
        WaybackSelection,
        newest_wayback_captures,
        payload_sha1,
        read_wayback_index,
        read_wayback_replay,
        wayback_replay_url,
    )
    from spicy_docs.transport.captured import CapturedBodyResponse

    assert callable(WaybackFallback)
    original_url = "https://www.finance.senate.gov/imo/media/doc/testimony.pdf"
    ts = "20240519143000"
    pdf_payload = b"%PDF-1.4\n1 0 obj << /Title (Access Denied Just a moment Cloudflare) >> endobj\n%%EOF\n"
    digest = payload_sha1(pdf_payload)

    # a648e60d: a PDF/binary body containing wall phrases must never be classified as an error page.
    assert detect_error_page(pdf_payload, status_code=200, media_types=("application/pdf",), source_format="pdf") is None

    scope = WaybackCdxScope(url=original_url, media_type="application/pdf")
    cdx_filtered = json.dumps([["timestamp", "original", "digest"], [ts, original_url, digest]]).encode()
    newest = newest_wayback_captures(cdx_filtered, scope)
    assert newest[("www.finance.senate.gov", "/imo/media/doc/testimony.pdf")].digest == digest

    selection = WaybackSelection(original_url=original_url, day="20240519")
    cdx_exact = json.dumps([
        ["urlkey", "timestamp", "original", "mimetype", "statuscode", "digest", "length"],
        ["gov,senate,finance)/imo/media/doc/testimony.pdf", ts, original_url, "application/pdf", "200", digest, "96"],
    ]).encode()
    idx_resp = CapturedBodyResponse(
        requested_url=selection.index_url,
        resolved_url=selection.index_url,
        status_code=200,
        content_type="application/json",
        observed_at="2026-11-18T22:00:00Z",
        body=cdx_exact,
    )
    idx_read = read_wayback_index(idx_resp, selection)
    assert len(idx_read.candidates) == 1
    replay_url = wayback_replay_url(original_url, ts)
    replay_resp = CapturedBodyResponse(
        requested_url=replay_url,
        resolved_url=replay_url,
        status_code=200,
        content_type="application/pdf",
        observed_at="2026-11-18T22:00:05Z",
        body=pdf_payload,
    )
    replay = read_wayback_replay(replay_resp, selection, idx_resp, idx_read.candidates[0])
    assert replay.payload_digest == digest
    assert replay.receipt_fields()["original_publisher_url"] == original_url


def test_opt_in_reader_opens_only_unencrypted_pdf_bytes():
    reader = OptInPdfReader(native_inhibit_spaces=True)
    with pytest.raises(ValueError, match="application/pdf only"):
        with reader.open(b"\x89PNG\r\n\x1a\n", "image/png"):
            pytest.fail("an image must not open")
    doc = pymupdf.open()
    doc.new_page()
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    doc.close()
    with pytest.raises(ExtractionError, match="encrypted PDF"):
        with reader.open(locked, "application/pdf"):
            pytest.fail("an encrypted PDF must not open")
    with pytest.raises(ExtractionError, match="not application/pdf"):
        with reader.open(b"<html><body>Not a PDF</body></html>", "application/pdf"):
            pytest.fail("markup masquerading as PDF must not open")


def test_pdf_reading_versions_and_invalid_box_and_vision_band_edge_controls(monkeypatch):
    from hashlib import sha256
    import math
    from spicy_docs.extraction.model import RAW_RGB, Box, Raster
    from spicy_docs.extraction.ocr import AppleVision
    from congress_api.lake.reading_versions import (
        BODY_TEXT_DECLARATIONS,
        PDF_NATIVE_SPACING_SYMBOL_REPAIR_DECLARATION,
        PDF_NATIVE_SPACING_SYMBOL_REPAIR_VERSION,
        PDF_TESSERACT_300DPI_RECOVERY_DECLARATION,
        PDF_TESSERACT_300DPI_RECOVERY_VERSION,
        PDF_TESSERACT_SELECTIVE_RECOVERY_DECLARATION,
        PDF_TESSERACT_SELECTIVE_RECOVERY_VERSION,
        READING_VERSIONS,
    )

    assert READING_VERSIONS["pdf_text"] == sha256(BODY_TEXT_DECLARATIONS["pdf_text"].encode()).hexdigest()
    assert PDF_TESSERACT_SELECTIVE_RECOVERY_VERSION == sha256(
        PDF_TESSERACT_SELECTIVE_RECOVERY_DECLARATION.encode()
    ).hexdigest()
    assert PDF_TESSERACT_300DPI_RECOVERY_VERSION == sha256(
        PDF_TESSERACT_300DPI_RECOVERY_DECLARATION.encode()
    ).hexdigest()
    assert PDF_NATIVE_SPACING_SYMBOL_REPAIR_VERSION == sha256(
        PDF_NATIVE_SPACING_SYMBOL_REPAIR_DECLARATION.encode()
    ).hexdigest()
    current_pdf_ids = {
        READING_VERSIONS["pdf_text"],
        PDF_TESSERACT_SELECTIVE_RECOVERY_VERSION,
        PDF_TESSERACT_300DPI_RECOVERY_VERSION,
        PDF_NATIVE_SPACING_SYMBOL_REPAIR_VERSION,
    }
    assert len(current_pdf_ids) == 4
    historical_v12_pdf_ids = {
        "4d04558965d9baf630033c94857169bfddad68988fce34041a4a35a0c6ddd2a8",
        "5d84e2bca02998e7b509ec12d2b5c17ef12d9da8a76c3e4b8e1f487b6f7c8f82",
        "b345ac1cf8f88e2726a5de04cd92d470c3d83fbf490e9724b308797c6901a0f9",
    }
    assert current_pdf_ids.isdisjoint(historical_v12_pdf_ids)

    # Non-finite native coordinates (40, 50, +inf, 80) refuse as ExtractionError(invalid_box) across all three PDF policies.
    with pymupdf.open() as doc:
        pg = doc.new_page(width=400, height=500)
        pg.insert_text((80, 120), "Before\nUnlocated\nAfter" + " prose" * 20)
        pg.set_cropbox(pymupdf.Rect(50, 70, 350, 470))
        sample_pdf = doc.tobytes()

    original_get_text = pymupdf.Page.get_text

    def injected_get_text(page, option="text", **kwargs):
        raw = original_get_text(page, option, **kwargs)
        if option == "dict":
            coords = (40, 50, math.inf, 80)
            line = raw["blocks"][0]["lines"][1]
            line["bbox"] = coords
            line["spans"][0].update(text="Unlocated", bbox=coords, alpha=255)
        return raw

    monkeypatch.setattr(pymupdf.Page, "get_text", injected_get_text)
    for rule in (body_text.native_only(), native_inhibit_spaces_only(), tesseract_bounded_200dpi()):
        reading = body_text.pdf_text(sample_pdf, strategy=rule, page_deadline_seconds=15)
        assert reading.status == "error"
        assert reading.error_type == "failed_pages"
        assert reading.text is None
        assert reading.fields["failed_pages"] == [1]
        assert "invalid_box" in (reading.diagnostic or "")
    monkeypatch.setattr(pymupdf.Page, "get_text", original_get_text)

    # Under CT's 3-band Vision settings, an unmatched internal strip-edge line survives (PR 31).
    calls = []

    def injected_vision_engine(strip: Raster):
        idx = len(calls)
        calls.append(idx)
        if idx == 0:
            # Strip 0 bottom edge in Vision bottom-left coords: middle > strip core end, lower within 0.005*height of bottom.
            return [("edge observation", 1.0, [0.1, 0.002, 0.5, 0.03])]
        return []

    vis = AppleVision(recognition_level="accurate", language_correction=False, bands=3, engine=injected_vision_engine)
    blank_rgb = Raster(b"\xff" * (100 * 300 * 3), 100, 300, Box(), RAW_RGB)
    recognized = vis.recognize(blank_rgb)
    assert recognized.text == "edge observation"


def test_cleanup_review_flags_a_dropped_native_block_with_surviving_furniture():
    from hashlib import sha256
    from congress_api.lake.text_quality import measure_quality

    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((60, 40), "Committee report")
        page.insert_text((60, 110), "The committee requires the department to inspect each site before renewal.")
        page.insert_text((60, 140), "The district must publish the inspection findings and provide a written response.")
        page.insert_text((60, 720), "17")
        source = doc.tobytes()
    with OptInPdfReader().open(source, "application/pdf") as pdf:
        observed = pdf.page(1).native().text

    body_sha = sha256(source).hexdigest()
    header, first, second, footer = observed.splitlines()
    for output, omitted in (
        (observed, False),
        ("\n\n".join((header, first.replace("each site", "each\nsite"), second, footer)), False),
        (f"{header}\n{footer}", True),
    ):
        digest = sha256(output.encode()).hexdigest()
        identity = dict(body_sha256=body_sha, parser="pdf_text", parser_version="test",
                        text_sha256=digest, output_sha256=digest, source_format="pdf",
                        scope="page", page_number=1, source_page_count=1,
                        intermediate_body_sha256=body_sha, intermediate_page_number=1,
                        intermediate_scope="page", intermediate_kind="native")
        review = measure_quality(identity, text=output, intermediate=observed)
        assert review["fts_triage"]["band"] == ("review_later" if omitted else "no_obvious_failure_detected")
        assert ("substantial_intermediate_difference" in review["fts_triage"]["reasons"]) == omitted
        assert ("possible_cleanup_loss" in review["signals"]) == omitted


@pytest.mark.parametrize(("case", "missing_tokens"), [
    ("complete", 0), ("reflow", 0), ("omitted", 23), ("short_page", 0),
    ("moved", 0), ("lost_duplicate", 34), ("inspection_omitted", 23), ("moved_and_omitted", 23),
    ("lost_duplicate_with_moved_sentence", 34),
])
def test_selective_review_of_recognition_on_a_scanned_page(case, missing_tokens, tmp_path):
    from contextlib import closing
    from hashlib import sha256
    import json
    from pathlib import Path
    from unittest.mock import Mock

    from spicy_docs.extraction.model import Recognition
    from congress_api.cli.text_quality import measure_cases

    header, footer = "Committee report", "Page 17"
    passage = [
        "The committee requires the department to inspect each site",
        "before renewal. The district must publish the inspection",
        "findings and provide a written response.",
    ]
    lines = [header, *passage, footer] if case != "short_page" else [header, footer]
    # Plant changes at the primary image backend. The independent OCR reads
    # the source ink, including both copies in the lost-duplicate control.
    observed = "\n".join(lines)
    if case == "omitted":
        observed = f"{header}\n{footer}"
    elif case == "reflow":
        observed = observed.replace("\n", " ").replace("each site", "each\nsite")
    elif case in {"moved", "lost_duplicate", "inspection_omitted", "moved_and_omitted",
                  "lost_duplicate_with_moved_sentence"}:
        # Excerpts from report page 151. The inspection and response share individual words.
        inspection = [
            "conducted remote inspections of the ICE hotel facilities to",
            "assess compliance by the contractor, Endeavors, with ICE",
            "detention standards and COVID-19 requirements.",
        ]
        findings = [
            "at six hotels that went largely unused between April and",
            "June 2021. ICE's sole source contract with Endeavors",
            "resulted in millions of dollars being spent on unused",
            "hotel space. In addition, Endeavors did not meet new",
            "healthcare protocols or ensure proper COVID-19 testing",
            "for families.",
        ]
        response = [
            "ICE Response",
            "ICE concurred with one recommendation and did not",
            "concur with three recommendations. One",
            "recommendation was resolved and closed, and three",
            "recommendations were administratively closed. See",
            "Appendix B for ICE's full response.",
        ]
        if case == "lost_duplicate_with_moved_sentence":
            sentence = ["Agency officials confirmed that one recommendation",
                        "was resolved after the committee published its formal notice."]
            lines = [*response, *response, *sentence, *findings]
            observed = "\n".join([*findings, *sentence, *response])
        else:
            copies = 2 if case == "lost_duplicate" else 1
            heading = "What We Recommend"
            lines = [header, *inspection, heading, *findings, *(response * copies), footer]
            retained_inspection = [] if case in {"inspection_omitted", "moved_and_omitted"} else inspection
            sections = [*findings, *response] if case == "inspection_omitted" else [*response, *findings]
            observed = "\n".join([header, *retained_inspection, heading, *sections, footer])
    source = _make_scanned_pdf(lines)
    reader = OptInPdfReader(dpi=150)
    with reader.open(source, "application/pdf") as pdf:
        page = pdf.page(1)
        assert not page.native().text.strip()
        raster = page.render()
    with closing(TesseractBackend()) as secondary:
        reference = secondary.recognize(raster).text
    assert " ".join(reference.split()) == " ".join(lines)

    primary = Mock()
    primary.recognize.return_value = Recognition(observed, {}, None)
    events = []
    reading = body_text.pdf_text(source, strategy=body_text.page_rule(primary, reader),
                                 page_deadline_seconds=30, evidence=events.append)
    primary.recognize.assert_called_once_with(raster)
    assert reading.status == "completed" and reading.ocr_pages == (1,)
    [extracted] = [event for event in events if event["event"] == "page_extracted"]
    assert extracted["pre_cleanup_text"] == observed
    assert reading.text.split() == observed.split()

    body_sha = sha256(source).hexdigest()
    output = tmp_path / "page.txt"
    output.write_text(reading.text, encoding="utf-8")
    reference_file = tmp_path / "secondary-ocr.txt"
    reference_file.write_text(reference, encoding="utf-8")
    digest = sha256(output.read_bytes()).hexdigest()
    manifest = tmp_path / "cases.jsonl"
    manifest.write_text(json.dumps(dict(
        case_id=case, body_sha256=body_sha, parser="pdf_text", parser_version="test",
        source_format="pdf", source_state="retained", scope="page", page_number=1, source_page_count=1,
        text_sha256=digest, output_sha256=digest, output_path=str(output),
        intermediate_kind="independent_ocr", intermediate_path=str(reference_file),
        intermediate_sha256=sha256(reference_file.read_bytes()).hexdigest(),
        intermediate_body_sha256=body_sha, intermediate_scope="page", intermediate_page_number=1,
    )))
    result = measure_cases(manifest, tmp_path / "review")
    review = json.loads(Path(result["measurements"]).read_text())
    proposal = json.loads(Path(result["proposals"]).read_text())["proposal"]
    comparison = review["axes"]["recognition"]["independent_ocr_comparison"]
    assert comparison["status"] == "measured"
    assert review["axes"]["recognition"]["largest_unmatched_ocr_passage_tokens"] == missing_tokens
    if case == "omitted":
        assert any(" ".join(change["intermediate_slice"].split()) == " ".join(passage)
                   for change in comparison["changes"])
    elif case in {"moved", "lost_duplicate"}:
        assert [change["operation"] for change in comparison["changes"]] == ["insert", "delete"]
        assert comparison["removed_content_tokens"] == copies * 34
    elif case == "lost_duplicate_with_moved_sentence":
        deleted, inserted = comparison["changes"]
        assert deleted["intermediate_slice"].split() == " ".join(response * 2 + sentence).split()
        assert inserted["output_slice"].split() == " ".join(sentence + response).split()
    elif case in {"inspection_omitted", "moved_and_omitted"}:
        assert any(" ".join(change["intermediate_slice"].split()) == " ".join(inspection)
                   for change in comparison["changes"])
        assert comparison["removed_content_tokens"] == (57 if case == "moved_and_omitted" else 23)
    else:
        assert comparison["changes"] == []
    if missing_tokens:
        assert review["signals"] == ["possible_missing_content"]
        assert review["fts_triage"]["reasons"] == ["possible_missing_content"]
        assert review["fts_triage"]["band"] == "review_later"
        assert proposal["action"] == "manual_review"
    else:
        assert review["signals"] == review["fts_triage"]["reasons"] == []
        assert review["fts_triage"]["band"] == "no_obvious_failure_detected"
        assert proposal["action"] == "keep"


def test_moved_paragraph_across_repetitive_table_matches_in_under_50ms():
    from hashlib import sha256
    from timeit import repeat

    from congress_api.lake.text_assessment import assess_text
    from congress_api.lake.text_quality import _largest_unmatched_ocr_passage, assessment_facts, measure_quality

    def table(prefix):
        return "\n".join(f"current year approved amount {prefix}{row}" for row in range(160))

    paragraph = " ".join(f"The committee reviewed funding for district {i}" for i in range(28))
    reference = f"{table('old')}\n{paragraph}"
    output = f"{paragraph}\n{table('new')}"
    digest = sha256(output.encode()).hexdigest()
    identity = dict(body_sha256="a"*64, parser="pdf_text", parser_version="test", text_sha256=digest,
                    output_sha256=digest, source_format="pdf", source_state="retained",
                    scope="page", page_number=1, source_page_count=1,
                    intermediate_kind="independent_ocr", intermediate_body_sha256="a"*64,
                    intermediate_scope="page", intermediate_page_number=1)

    measured = measure_quality(identity, text=output, intermediate=reference)
    recognition = measured["axes"]["recognition"]
    comparison = recognition["independent_ocr_comparison"]
    assert comparison["intermediate_tokens"] == comparison["output_tokens"] == 996
    assert comparison["removed_content_tokens"] == comparison["inserted_tokens"] == 800
    # Only the identifier in each row differs. Its neighbors still form an intact four-token span.
    assert recognition["largest_unmatched_ocr_passage_tokens"] == 1
    evidence = dict(stage="measurement", path="/measure.json", sha256="b"*64, locator="line 1")
    assert assess_text(assessment_facts(measured, evidence))["action"] == "keep"

    # Time span matching on the actual ordered diff, excluding the upstream alignment.
    elapsed = min(repeat(lambda: _largest_unmatched_ocr_passage(comparison["changes"]), number=1, repeat=3))
    assert elapsed < 0.05, f"span matching took {elapsed:.4f}s on the 996-token page"


@pytest.mark.parametrize("angle", [90, 180, 270])
@pytest.mark.parametrize("raw_rgb", [False, True])
def test_adaptive_rotation_is_lossless_and_scoped_to_the_named_page(angle, raw_rgb):
    import io
    from PIL import Image
    from spicy_docs.extraction import DefaultReader
    from spicy_docs.extraction.model import RAW_RGB

    with pymupdf.open() as pdf:
        for width in (288, 72):
            page = pdf.new_page(width=width, height=144)
            page.draw_rect((9, 12, 37, 61), fill=(0.2, 0.7, 0.3))
        source = pdf.tobytes()

    options = dict(dpi=72, adaptive_max_pixels=True, max_pixels=21_000, raw_rgb=raw_rgb)
    with OptInPdfReader(**options, rotate_ccw_pages={1: angle}).open(source, "application/pdf") as doc:
        rotated = doc.page(1).render()
        neighbor = doc.page(2).render()
    # The first page fits at 50 DPI. Its neighbor fits at the requested 72 DPI.
    with DefaultReader(dpi=50, raw_rgb=True).open(source, "application/pdf") as doc:
        base = doc.page(1).render()
    with DefaultReader(dpi=72, raw_rgb=raw_rgb).open(source, "application/pdf") as doc:
        assert neighbor == doc.page(2).render()
    original = Image.frombytes("RGB", (base.width, base.height), base.data)
    expected = original.rotate(angle, expand=True)
    assert (rotated.width, rotated.height) == expected.size
    assert rotated.media_type == (RAW_RGB if raw_rgb else "image/png")
    actual = rotated.data if raw_rgb else Image.open(io.BytesIO(rotated.data)).tobytes()
    assert actual == expected.tobytes()
