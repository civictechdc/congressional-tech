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
from copy import copy
from importlib.metadata import version
import math
import os

from spicy_docs.extraction import DefaultReader, NativeOrOcr
from spicy_docs.extraction.model import Raster
from spicy_docs.extraction.ocr import Tesseract
from spicy_docs.extraction.pages import _PDF, _PDFPage, _raster

from congress_api.parsers.body_text import OCR_MIN_CHARS, PageRule, gpo_page, page_rule

DEFAULT_TESSDATA_DIR = '/opt/homebrew/share/tessdata'
PORTABLE_STRATEGY = 'congress_api.parsers.pdf_opt_in:portable_tesseract_200dpi'
_open_default_reader = DefaultReader.open


class TesseractBackend(Tesseract):
    """Use the shared recognizer with CT's historical model-directory default."""

    def __init__(self, *, language='eng', model='fast', tessdata_dir=None,
                 page_segmentation_mode=3, engine=None):
        os.environ.setdefault('OMP_THREAD_LIMIT', '1')
        directory = tessdata_dir if tessdata_dir is not None else (os.environ.get('TESSDATA_PREFIX') or DEFAULT_TESSDATA_DIR)
        super().__init__(language=language, model=model, tessdata_dir=directory,
                         page_segmentation_mode=page_segmentation_mode, engine=engine)


class _OptInPDFPage(_PDFPage):
    """Extends ``_PDFPage`` with adaptive pixel ceiling and CCW rotation; ``native_inhibit_spaces`` delegates to ``_PDFPage.native``."""

    def render(self) -> Raster:
        from PIL import Image

        dpi = self.reader.dpi
        rect = self.page.rect
        if self.reader.adaptive_max_pixels and rect.width > 0 and rect.height > 0:
            pixels = math.ceil(rect.width * dpi / 72) * math.ceil(rect.height * dpi / 72)
            if pixels > self.reader.max_pixels:
                scale = math.sqrt(self.reader.max_pixels * 0.985 / (rect.width * rect.height / 72**2))
                dpi = max(36, min(dpi, math.floor(scale)))
                while dpi > 36 and math.ceil(rect.width * dpi / 72) * math.ceil(rect.height * dpi / 72) > self.reader.max_pixels:
                    dpi -= 1

        rotation = self.reader.rotate_ccw_pages.get(self.number, 0)
        if dpi == self.reader.dpi and not rotation:
            return super().render()

        # The shared renderer checks the ceiling both before and after allocation.
        # Page-specific DPI and raw rotation input must not leak to sibling pages.
        reader = copy(self.reader)
        reader.dpi = dpi
        if rotation:
            reader.raw_rgb = True
        raster = _PDFPage(self.page, self.number, reader, self.unmapped).render()
        if not rotation:
            return raster
        transpose = {90: Image.Transpose.ROTATE_90, 180: Image.Transpose.ROTATE_180,
                     270: Image.Transpose.ROTATE_270}
        if rotation not in transpose:
            raise ValueError(f'Unsupported rotation angle: {rotation}')
        image = Image.frombytes('RGB', (raster.width, raster.height), raster.data)
        return _raster(image.transpose(transpose[rotation]), self.reader.raw_rgb)


class _OptInPDF(_PDF):
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
        with _open_default_reader(self, source, media_type) as pdf:
            yield _OptInPDF(pdf.document, self)


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


def portable_tesseract_200dpi() -> PageRule:
    """Portable incremental PDF rule pairing bounded 200 DPI Tesseract with multi-format body_text."""
    return tesseract_bounded_200dpi()


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
