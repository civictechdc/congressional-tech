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

from collections import Counter
from contextlib import contextmanager
import ctypes
import ctypes.util
import functools
import hashlib
from importlib.metadata import version
import io
import math
import os
from pathlib import Path
import platform
import threading
from typing import Any
import weakref

from spicy_docs.extraction import DefaultReader, NativeOrOcr
from spicy_docs.extraction.font_glyphs import counts, map_line, unmapped_by_font
from spicy_docs.extraction.model import RAW_RGB, Box, ExtractionError, ProcessingIssue, Raster, Recognition, TextBlock
from spicy_docs.extraction.pages import _display_box, _PDFPage

from congress_api.parsers.body_text import OCR_MIN_CHARS, PageRule, gpo_page, page_rule

DEFAULT_TESSDATA_DIR = '/opt/homebrew/share/tessdata'
_TESSDATA = {
    ('eng', 'best'): ('8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba', 15_400_601),
    ('eng', 'fast'): ('7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2', 4_113_088),
}
_TESSERACT_PSM = frozenset({3, 4, 5, 6, 7, 8, 9, 10, 11, 13})
_TEXTLINE, _LSTM_ONLY = 2, 1
_P, _I = ctypes.c_void_p, ctypes.c_int
_TESS_API = {
    'TessVersion': ([], ctypes.c_char_p),
    'TessBaseAPICreate': ([], _P),
    'TessBaseAPIDelete': ([_P], None),
    'TessBaseAPISetVariable': ([_P, ctypes.c_char_p, ctypes.c_char_p], _I),
    'TessBaseAPIInit5': ([_P, ctypes.c_char_p, _I, ctypes.c_char_p, _I, _P, _I, _P, _P, ctypes.c_size_t, _I], _I),
    'TessBaseAPISetPageSegMode': ([_P, _I], None),
    'TessBaseAPISetImage': ([_P, ctypes.c_char_p, _I, _I, _I, _I], None),
    'TessBaseAPIRecognize': ([_P, _P], _I),
    'TessBaseAPIClear': ([_P], None),
    'TessBaseAPIGetIterator': ([_P], _P),
    'TessResultIteratorGetPageIterator': ([_P], _P),
    'TessPageIteratorBoundingBox': ([_P, _I, *[ctypes.POINTER(_I)] * 4], _I),
    'TessResultIteratorGetUTF8Text': ([_P, _I], _P),
    'TessResultIteratorConfidence': ([_P, _I], ctypes.c_float),
    'TessResultIteratorNext': ([_P, _I], _I),
    'TessResultIteratorDelete': ([_P], None),
    'TessDeleteText': ([_P], None),
}
_TESS_LOCK = threading.Lock()


def _clamp01(val: float) -> float:
    return max(0.0, min(1.0, float(val)))


def _norm_box(x0: float, y0: float, x1: float, y1: float) -> Box | None:
    nx0, ny0, nx1, ny1 = _clamp01(x0), _clamp01(y0), _clamp01(x1), _clamp01(y1)
    if nx1 <= nx0 or ny1 <= ny0:
        return None
    return Box(nx0, ny0, nx1, ny1)


def _rgb_samples(image: Raster) -> bytes:
    if image.media_type == RAW_RGB:
        expected = image.width * image.height * 3
        if len(image.data) != expected:
            raise ExtractionError(f'RAW_RGB length {len(image.data)} != {expected}')
        return image.data
    from PIL import Image
    with Image.open(io.BytesIO(image.data)) as img:
        rgb = img.convert('RGB')
        if (rgb.width, rgb.height) != (image.width, image.height):
            raise ExtractionError('Decoded image dimensions differ from Raster metadata')
        return rgb.tobytes()


def _leptonica_version(lib) -> str | None:
    try:
        read, free = lib.getLeptonicaVersion, lib.lept_free
    except AttributeError:
        return None
    read.restype, free.argtypes = _P, [_P]
    text = read()
    try:
        return ctypes.string_at(text).decode()
    finally:
        free(text)


@functools.cache
def _load_libtesseract() -> tuple[ctypes.CDLL, dict[str, str | None]] | dict[str, str]:
    reasons = {}
    candidates = dict.fromkeys(
        filter(None, (ctypes.util.find_library('tesseract'), 'libtesseract.so.5', '/opt/homebrew/lib/libtesseract.dylib'))
    )
    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
            for symbol, (arguments, result) in _TESS_API.items():
                fn = getattr(lib, symbol)
                fn.argtypes, fn.restype = arguments, result
        except (OSError, AttributeError) as error:
            reasons[name] = str(error)
            continue
        handle = lib.TessBaseAPICreate()
        lib.TessBaseAPISetVariable(handle, b'debug_file', os.devnull.encode())
        lib.TessBaseAPIDelete(handle)
        return lib, {'version': lib.TessVersion().decode(), 'leptonica': _leptonica_version(lib)}
    return reasons


def _libtesseract() -> tuple[ctypes.CDLL, dict[str, str | None]]:
    with _TESS_LOCK:
        found = _load_libtesseract()
    if isinstance(found, dict):
        raise ExtractionError('Tesseract requires libtesseract 5', details={'tried': found})
    return found


def _tessdata(language: str, variant: str, directory: str | os.PathLike | None) -> tuple[bytes, dict[str, Any]]:
    directory = directory if directory is not None else (os.environ.get('TESSDATA_PREFIX') or DEFAULT_TESSDATA_DIR)
    name, origin = f'{language}.traineddata', f'github.com/tesseract-ocr/tessdata_{variant}'
    path = Path(directory) / name
    try:
        data = path.read_bytes()
    except OSError as error:
        raise ExtractionError(f'Tesseract {variant} model {path} is unreadable ({error.strerror})',
                              details={'path': str(path)}) from None
    found = hashlib.sha256(data).hexdigest(), len(data)
    if found != _TESSDATA[language, variant]:
        raise ExtractionError(f'{path} does not match pinned {origin} {name}',
                              details={'path': str(path), 'sha256': found[0], 'bytes': found[1]})
    return data, {'sha256': found[0], 'bytes': found[1], 'source': origin}


class _TesseractHandle:
    def __init__(self, lib, data: bytes, language: str, psm: int):
        self.lib, self.handle = lib, (handle := lib.TessBaseAPICreate())
        self.close = weakref.finalize(self, lib.TessBaseAPIDelete, handle)
        if lib.TessBaseAPIInit5(handle, data, len(data), language.encode(), _LSTM_ONLY, None, 0, None, None, 0, 0):
            self.close()
            raise ExtractionError('libtesseract refused model initialization', details={'language': language})
        lib.TessBaseAPISetPageSegMode(handle, psm)

    def __call__(self, image: Raster) -> list[tuple[str, float, list[int]]]:
        lib, handle, detections = self.lib, self.handle, []
        samples = _rgb_samples(image)
        lib.TessBaseAPISetImage(handle, samples, image.width, image.height, 3, image.width * 3)
        try:
            if lib.TessBaseAPIRecognize(handle, None):
                raise ExtractionError('Tesseract recognition failed', details={'width': image.width, 'height': image.height})
            if not (lines := lib.TessBaseAPIGetIterator(handle)):
                return detections
            try:
                page, edges = lib.TessResultIteratorGetPageIterator(lines), [ctypes.c_int() for _ in range(4)]
                while True:
                    if lib.TessPageIteratorBoundingBox(page, _TEXTLINE, *map(ctypes.byref, edges)):
                        ptr = lib.TessResultIteratorGetUTF8Text(lines, _TEXTLINE)
                        try:
                            decoded = ctypes.string_at(ptr).decode('utf-8', errors='replace') if ptr else ''
                        finally:
                            if ptr:
                                lib.TessDeleteText(ptr)
                        conf = float(lib.TessResultIteratorConfidence(lines, _TEXTLINE))
                        detections.append((decoded, conf, [e.value for e in edges]))
                    if not lib.TessResultIteratorNext(lines, _TEXTLINE):
                        return detections
            finally:
                lib.TessResultIteratorDelete(lines)
        finally:
            lib.TessBaseAPIClear(handle)


class TesseractBackend:
    """In-process libtesseract 5 LSTM recognizer pinned to ``tessdata_fast`` SHA-256."""

    def __init__(self, *, language: str = 'eng', model: str = 'fast', tessdata_dir: str | None = None,
                 page_segmentation_mode: int = 3, engine=None):
        if (language, model) not in _TESSDATA:
            raise ValueError(f'Unsupported Tesseract model {(language, model)!r}')
        if type(page_segmentation_mode) is not int or page_segmentation_mode not in _TESSERACT_PSM:
            raise ValueError(f'Unsupported page_segmentation_mode: {page_segmentation_mode}')
        self.language, self.model, self.tessdata_dir, self.psm = language, model, tessdata_dir, page_segmentation_mode
        self.engine, self._injected, self._model_file, self._versions = engine, engine is not None, None, {}

    def configuration(self) -> dict[str, Any]:
        return {
            'backend': 'tesseract',
            'version': self._versions.get('version'),
            'leptonica': self._versions.get('leptonica'),
            'machine': platform.machine(),
            'language': self.language,
            'model': self.model,
            'model_file': self._model_file,
            'page_segmentation_mode': self.psm,
            'engine_mode': 'lstm-only',
            'engine_injected': self._injected,
        }

    def require_reproducible_identity(self) -> dict[str, Any]:
        if self._injected:
            raise ValueError('Injected Tesseract engine has no reproducible identity')
        self._engine()
        return self.configuration()

    def _engine(self):
        if self.engine is None:
            lib, versions = _libtesseract()
            data, model_file = _tessdata(self.language, self.model, self.tessdata_dir)
            self.engine = _TesseractHandle(lib, data, self.language, self.psm)
            self._versions, self._model_file = versions, model_file
        return self.engine

    def recognize(self, image: Raster) -> Recognition:
        detections = self._engine()(image)
        width, height = image.width, image.height
        blocks = tuple(
            TextBlock(
                text.rstrip('\n'),
                _norm_box(left / width, top / height, right / width, bottom / height),
                conf / 100.0,
            )
            for text, conf, (left, top, right, bottom) in detections
            if text.strip()
        )
        raw = {'detections': detections, 'coordinates': 'image pixels; top-left origin; left, top, right, bottom'}
        return Recognition('\n'.join(b.text for b in blocks), self.configuration(), raw, blocks)

    def close(self) -> None:
        if not self._injected and self.engine is not None:
            self.engine.close()
            self.engine, self._model_file, self._versions = None, None, {}


class _OptInPDFPage(_PDFPage):
    """Extends ``_PDFPage`` with opt-in ``native_inhibit_spaces``, adaptive pixel ceiling, and CCW rotation."""

    def native(self):
        if not getattr(self.reader, 'native_inhibit_spaces', False):
            return super().native()
        import pymupdf
        from spicy_docs.extraction.pages import _unmapped_issues

        flags = (pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES) | pymupdf.TEXT_INHIBIT_SPACES
        raw = self.page.get_text('dict', flags=flags)
        unmapped, unreadable = unmapped_by_font(self.page.parent, self.page.get_fonts(), self.unmapped)
        blocks = []
        issues = [
            ProcessingIssue('unmapped-glyph-check-skipped', f'{name}: font dictionary or Unicode map unreadable')
            for name in unreadable
        ]
        tally: Counter = Counter()
        width, height = self.page.rect.width, self.page.rect.height
        for block in raw['blocks']:
            for line in block.get('lines', []):
                text = map_line(line['spans'], tally, line['dir'])
                box = _display_box(self.page, line['bbox'], width, height)
                if box is None:
                    if not text.strip():
                        continue
                    raise ExtractionError('native text falls outside displayed page bounds', details=line)
                issues.extend(_unmapped_issues(line['spans'], unmapped, len(blocks), box))
                blocks.append(TextBlock(text, box))
        for glyph in counts(self.number, tally):
            mapped = glyph.replacement is not None
            issues.append(
                ProcessingIssue(
                    'font-glyph-mapped' if mapped else 'font-glyph-unresolved',
                    f'{glyph.rule}: {glyph.font} {glyph.original!r} -> '
                    f"{glyph.replacement if mapped else 'kept'!r} x{glyph.count}",
                )
            )
        cfg = {'backend': 'pymupdf', 'version': version('pymupdf'), 'sort': False, 'inhibit_spaces': True}
        return Recognition('\n'.join(b.text for b in blocks), cfg, raw, tuple(blocks), issues=tuple(issues))

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
        super().__init__(dpi=dpi, max_pixels=max_pixels, table_strategy=table_strategy, raw_rgb=raw_rgb)
        if not isinstance(native_inhibit_spaces, bool):
            raise TypeError('native_inhibit_spaces must be bool')
        if not isinstance(adaptive_max_pixels, bool):
            raise TypeError('adaptive_max_pixels must be bool')
        self.native_inhibit_spaces = native_inhibit_spaces
        self.adaptive_max_pixels = adaptive_max_pixels
        self.rotate_ccw_pages = dict(rotate_ccw_pages or {})

    @contextmanager
    def open(self, source: bytes, media_type: str):
        if media_type == 'application/pdf':
            import pymupdf
            with pymupdf.open(stream=source, filetype='pdf') as document:
                if document.needs_pass:
                    raise ExtractionError('encrypted PDF requires decryption before extraction')
                yield _OptInPDF(document, self)
        else:
            with super().open(source, media_type) as images:
                yield images


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
