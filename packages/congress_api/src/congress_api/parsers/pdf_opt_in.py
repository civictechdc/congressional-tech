"""Opt-in PDF extraction backends and readers for reviewed recovery cohorts.

Default ``pdf_text`` extraction and its declared ``READING_VERSIONS['pdf_text']``
remain completely unchanged. These opt-in policies bind explicit versioned
configurations for:
- CPU Tesseract 5.5.4 LSTM recognition (pinned ``tessdata_fast`` SHA-256)
- Bounded-pixel adaptive DPI rendering for oversized 72-DPI scan pages (``memory17``)
- Lossless raster orientation repair for sideways scanned forms
- PyMuPDF ``TEXT_INHIBIT_SPACES`` native spacing preservation (``native_inhibit_spaces``)
"""
from __future__ import annotations

from contextlib import contextmanager
from importlib.metadata import version
import io
import math
import os

from spicy_docs.extraction import DefaultReader, NativeOrOcr
from spicy_docs.extraction.model import RAW_RGB, Box, ExtractionError, Raster
from spicy_docs.extraction.ocr import Tesseract
from spicy_docs.extraction.pages import _PDFPage

from congress_api.parsers.body_text import OCR_MIN_CHARS, PageRule, gpo_page, page_rule

DEFAULT_TESSDATA_DIR = '/opt/homebrew/share/tessdata'


class TesseractBackend(Tesseract):
    """Use the shared recognizer with CT's historical model-directory default."""

    def __init__(self, *, language='eng', model='fast', tessdata_dir=None,
                 page_segmentation_mode=3, engine=None):
        directory = tessdata_dir if tessdata_dir is not None else (os.environ.get('TESSDATA_PREFIX') or DEFAULT_TESSDATA_DIR)
        super().__init__(language=language, model=model, tessdata_dir=directory,
                         page_segmentation_mode=page_segmentation_mode, engine=engine)


class _OptInPDFPage(_PDFPage):
    """Extends ``_PDFPage`` with adaptive pixel ceiling and CCW rotation; ``native_inhibit_spaces`` delegates to ``_PDFPage.native``."""

    def render(self) -> Raster:
        import pymupdf
        from PIL import Image

        w_pt, h_pt = float(self.page.rect.width), float(self.page.rect.height)
        eff_dpi = self.reader.dpi
        if getattr(self.reader, 'adaptive_max_pixels', False) and w_pt > 0 and h_pt > 0:
            est_px = math.ceil(w_pt * eff_dpi / 72.0) * math.ceil(h_pt * eff_dpi / 72.0)
            if est_px > self.reader.max_pixels:
                scale = math.sqrt((self.reader.max_pixels * 0.985) / (w_pt * h_pt / (72.0 * 72.0)))
                eff_dpi = max(36, min(eff_dpi, int(math.floor(scale))))
                while eff_dpi > 36 and math.ceil(w_pt * eff_dpi / 72.0) * math.ceil(h_pt * eff_dpi / 72.0) > self.reader.max_pixels:
                    eff_dpi -= 1
        # Refuse before PyMuPDF allocates the raster, including at the minimum
        # adaptive DPI. The post-render check still guards unexpected dimensions.
        self.reader.check_pixels(math.ceil(w_pt * eff_dpi / 72.0), math.ceil(h_pt * eff_dpi / 72.0))
        pix = self.page.get_pixmap(dpi=eff_dpi, colorspace=pymupdf.csRGB, alpha=False)
        self.reader.check_pixels(pix.width, pix.height)
        rot_ccw = getattr(self.reader, 'rotate_ccw_pages', {}).get(self.number, 0)
        if rot_ccw:
            img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            if rot_ccw == 90:
                img = img.transpose(Image.Transpose.ROTATE_90)
            elif rot_ccw == 180:
                img = img.transpose(Image.Transpose.ROTATE_180)
            elif rot_ccw == 270:
                img = img.transpose(Image.Transpose.ROTATE_270)
            else:
                raise ValueError(f'Unsupported rotation angle: {rot_ccw}')
            if self.reader.raw_rgb:
                return Raster(img.tobytes(), img.width, img.height, Box(), RAW_RGB)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return Raster(buf.getvalue(), img.width, img.height, Box())
        if self.reader.raw_rgb:
            return Raster(bytes(pix.samples), pix.width, pix.height, Box(), RAW_RGB)
        return Raster(pix.tobytes('png'), pix.width, pix.height, Box())


class _OptInPDF:
    def __init__(self, document, reader):
        self.document, self.reader, self.page_count = document, reader, len(document)
        self.unmapped: dict[int, frozenset[int] | None] = {}

    def page(self, number: int) -> _OptInPDFPage:
        return _OptInPDFPage(self.document[number - 1], number, self.reader, self.unmapped)


class OptInPdfReader(DefaultReader):
    """Opt-in PDF reader supporting ``native_inhibit_spaces``, adaptive pixel ceiling, and page CCW rotation."""

    def __init__(
        self,
        *,
        dpi: int = 200,
        max_pixels: int = 20_000_000,
        table_strategy: str = 'lines',
        raw_rgb: bool = True,
        native_inhibit_spaces: bool = False,
        adaptive_max_pixels: bool = False,
        rotate_ccw_pages: dict[int, int] | None = None,
    ):
        super().__init__(
            dpi=dpi,
            max_pixels=max_pixels,
            table_strategy=table_strategy,
            raw_rgb=raw_rgb,
            native_inhibit_spaces=native_inhibit_spaces,
        )
        if not isinstance(adaptive_max_pixels, bool):
            raise TypeError('adaptive_max_pixels must be bool')
        self.adaptive_max_pixels = adaptive_max_pixels
        self.rotate_ccw_pages = dict(rotate_ccw_pages or {})

    @contextmanager
    def open(self, source: bytes, media_type: str):
        """Read supplied PDF bytes. An image is refused: every opt-in option acts on PDF pages
        and would be silently ignored, while the rule's checkpoint identity still claimed it."""
        if media_type != 'application/pdf':
            raise ValueError(f'OptInPdfReader reads application/pdf only, not {media_type}')
        import pymupdf
        with pymupdf.Document(stream=source, filetype='pdf') as document:
            if document.needs_pass:
                raise ExtractionError('encrypted PDF requires decryption before extraction')
            yield _OptInPDF(document, self)


def tesseract_300dpi() -> PageRule:
    """Opt-in native-first Tesseract 5.5.4 rule at 300 DPI (for dense scan / Vision-omission recovery)."""
    backend = TesseractBackend(language='eng', model='fast', page_segmentation_mode=3)
    identity = backend.require_reproducible_identity()
    reader = OptInPdfReader(dpi=300, max_pixels=20_000_000, raw_rgb=True)
    return page_rule(
        backend,
        reader,
        checkpoint_identity=dict(
            backend=identity,
            backend_implementation=f"spicy-docs-{version('spicy-docs')}",
            reader='OptInPdfReader',
            dpi=300,
            raw_rgb=True,
            max_pixels=reader.max_pixels,
            adaptive_max_pixels=False,
            native_inhibit_spaces=False,
        ),
    )


def tesseract_bounded_200dpi() -> PageRule:
    """Opt-in native-first Tesseract 5.5.4 rule with adaptive DPI cap <= 20M pixels (for oversized 72-DPI scans)."""
    backend = TesseractBackend(language='eng', model='fast', page_segmentation_mode=3)
    identity = backend.require_reproducible_identity()
    reader = OptInPdfReader(dpi=200, max_pixels=20_000_000, raw_rgb=True, adaptive_max_pixels=True)
    return page_rule(
        backend,
        reader,
        checkpoint_identity=dict(
            backend=identity,
            backend_implementation=f"spicy-docs-{version('spicy-docs')}",
            reader='OptInPdfReader',
            dpi=200,
            raw_rgb=True,
            max_pixels=reader.max_pixels,
            adaptive_max_pixels=True,
            native_inhibit_spaces=False,
        ),
    )


def native_inhibit_spaces_only() -> PageRule:
    """Opt-in native-only rule with ``native_inhibit_spaces=True`` (refuses scan pages with ``OcrRequired``)."""
    from congress_api.parsers.body_text import NoEngine
    reader = OptInPdfReader(dpi=200, max_pixels=20_000_000, raw_rgb=False, native_inhibit_spaces=True)
    return PageRule(
        NativeOrOcr(NoEngine(), min_chars=OCR_MIN_CHARS, normalize=gpo_page),
        reader,
        checkpoint_identity=dict(
            backend='none',
            reader='OptInPdfReader',
            dpi=200,
            raw_rgb=False,
            native_inhibit_spaces=True,
        ),
    )
