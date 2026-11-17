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
    assert rule.checkpoint_identity['backend_implementation'] == 'spicy-docs-0.85.0+cttesseract.20261117'
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
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_text(
        (72, 100),
        "Subcommittee on Courts, Intellectual Property, and the Internet Hearing Notice.",
        fontsize=12,
    )
    pg.insert_text(
        (72, 130),
        "Witnesses will testify regarding federal judicial administration and patent quality.",
        fontsize=12,
    )
    pdf_bytes = doc.tobytes()
    doc.close()

    reader = OptInPdfReader(native_inhibit_spaces=True)
    with reader.open(pdf_bytes, "application/pdf") as doc:
        assert doc.page_count == 1
    reading = body_text.pdf_text(pdf_bytes, strategy=native_inhibit_spaces_only(), page_deadline_seconds=15)
    assert reading.status == "completed"
    assert reading.ocr_pages == ()
    assert "Intellectual Property" in reading.text


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
