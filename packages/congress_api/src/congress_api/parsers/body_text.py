"""Body text of one decoded body, for the body-text parsers (data model §6.2, §6.6).

Pure derivations over bytes already read: no storage, catalog or provenance. The text
rules are spicy-docs': its markup reader for ``html_text`` and ``xml_text``, its
``DocumentExtractor`` plus ``normalize_gpo_pages`` for ``pdf_text``, and its WARC reader for
``warc``, whose payload the caller sniffs and routes back here. What this module adds is the
page rule's injection point and the bounds around it:

- **Page rule.** ``pdf_text`` takes a spicy-docs ``PageStrategy`` (``extract(page) ->
  PageContent``). A page is OCR'd when the strategy returns an observation other than
  ``native``. The default, :class:`NativeOnly`, reads the native layer and raises
  :class:`OcrRequired` for a page the declared rule sends to OCR, so a host without Vision
  leaves that body on the work list (§6.6: the version names its OCR engine).
- **Failed pages.** A page whose extraction fails is recorded in ``failed_pages`` and the
  reading is an ``error`` with no text: a partial text is never passed as complete.
- **Deadlines.** A per-page deadline runs inside the worker (``SIGALRM``, main thread only);
  it can interrupt Python code between bytecodes, not one long native call, which the
  supervisor's document deadline bounds instead.

Cost: O(B) in the body's bytes per rule; the PDF branch holds the body and one page's
objects at a time, plus the page texts (O(T)) that GPO normalization reads as a whole.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
import gzip
import hashlib
import importlib
import io
import platform
import signal
import subprocess
import threading
import zlib

from congress_api.parsers.archive_readings import fingerprint

TEXT_HEAD_BYTES = 2048
# The declared OCR page rule (reading_versions.BODY_TEXT_RULE names the same values): a page
# needs OCR when its native layer has fewer than this many non-whitespace characters and the
# page draws an image, or when a line carries a glyph code its font's Unicode map omits.
OCR_MIN_CHARS = 50
GARBLED_ISSUE = 'unmapped-glyph-code'
MARKUP_RENDITIONS = {'html_text': 'htm', 'xml_text': 'xml'}
PAYLOAD_PARSERS = {'pdf': 'pdf_text', 'html': 'html_text', 'xml': 'xml_text'}
DEFAULT_STRATEGY = 'congress_api.parsers.body_text:NativeOnly'


class OcrRequired(Exception):
    """A page needs OCR and this strategy has no engine: the body stays on the work list."""


class PageDeadline(Exception):
    """One page outlived the in-worker deadline: a resource failure, retried once (§6)."""


@dataclass(frozen=True)
class Reading:
    """One body's outcome: a narrow readings row, and its text when completed."""
    status: str
    error_type: str | None = None
    text: str | None = None
    page_offsets: tuple[int, ...] = ()
    ocr_pages: tuple[int, ...] = ()
    macos_build: str | None = None
    fields: dict = field(default_factory=dict)

    def row(self):
        """The readings columns §6.2 lets a body-text parser fill, with ``fields`` as strings."""
        text = self.text
        encoded = None if text is None else text.encode()
        return dict(status=self.status, error_type=self.error_type,
                    text_bytes=None if encoded is None else len(encoded),
                    text_head=None if encoded is None else encoded[:TEXT_HEAD_BYTES].decode('utf-8', 'ignore'),
                    # The fingerprint is over a native layer only: OCR output may differ by OS build.
                    fingerprint=fingerprint(text) if text is not None and not self.ocr_pages else None,
                    content_date=None,
                    fields=[dict(field=k, value=str(v)) for k, v in sorted(self.fields.items())])


def page_offsets(pages):
    """UTF-8 byte offset of each page's start in ``'\\n'.join(pages)``, spicy-docs' page join."""
    offsets, position = [], 0
    for page in pages:
        offsets.append(position)
        position += len(page.encode()) + 1
    return tuple(offsets)


def markup_text(data, parser):
    """``html_text``/``xml_text``: spicy-docs' markup reader, ``<pre>`` layout kept; one page."""
    from spicy_docs.extraction.body_text import rendition_text
    try:
        text = rendition_text(data, rendition=MARKUP_RENDITIONS[parser]).text
    except (ValueError, UnicodeError, RecursionError) as error:  # BodyTextError and MarkupReadError are ValueErrors
        return Reading('error', type(error).__name__)
    return Reading('completed', text=text, page_offsets=(0,), fields=dict(page_count=1))


def _has_image(page):
    """Whether a spicy-docs PDF page draws an image; unknown page kinds count as yes."""
    source = getattr(page, 'page', None)
    return True if source is None or not hasattr(source, 'get_images') else bool(source.get_images(full=False))


def needs_ocr(page, native):
    """The declared page rule over one native observation (module constants)."""
    if any(issue.code == GARBLED_ISSUE for issue in native.issues):
        return True
    return len(''.join(native.text.split())) < OCR_MIN_CHARS and _has_image(page)


@dataclass(frozen=True)
class NativeOnly:
    """Native text layer only; a page the rule sends to OCR raises :class:`OcrRequired`."""

    def extract(self, page):
        from spicy_docs.extraction import NativeText
        content = NativeText().extract(page)
        if needs_ocr(page, content.observations[0]):
            raise OcrRequired(page.number)
        return content


def load_strategy(spec):
    """Construct the page strategy a payload names as ``module:callable``, with no arguments."""
    module, name = spec.split(':', 1)
    return getattr(importlib.import_module(module), name)()


@contextmanager
def page_deadline(seconds, page_number):
    """Raise :class:`PageDeadline` in this thread after ``seconds``; off outside the main thread.

    ``SIGALRM`` reaches Python only between bytecodes, so one long native call runs to its end
    (the supervisor's document deadline bounds that). The previous handler is always restored.
    """
    if not seconds or threading.current_thread() is not threading.main_thread():
        yield
        return
    def expire(*_):
        raise PageDeadline(page_number)
    previous = signal.signal(signal.SIGALRM, expire)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class _PageRun:
    """Wrap a strategy: time each page, record OCR'd and failed pages, keep going after a failure."""

    def __init__(self, strategy, deadline_seconds):
        self.strategy, self.deadline = strategy, deadline_seconds
        self.ocr, self.failed, self.errors = [], [], {}

    def extract(self, page):
        from spicy_docs.extraction import PageContent
        try:
            with page_deadline(self.deadline, page.number):
                content = self.strategy.extract(page)
        except (OcrRequired, PageDeadline, MemoryError):
            raise
        except Exception as error:  # one page's own failure; the reading records it
            self.failed.append(page.number)
            self.errors[page.number] = type(error).__name__
            return PageContent((), ())
        if any(observation.id != 'native' for observation in content.observations):
            self.ocr.append(page.number)
        return content


def pdf_text(data, *, strategy, page_deadline_seconds):
    """``pdf_text``: one open of the PDF, each page through ``strategy``, then GPO normalization.

    Raises :class:`OcrRequired` or :class:`PageDeadline`; every other failure is a reading.
    """
    from spicy_docs.extraction import DocumentExtractor
    from spicy_docs.extraction.body_text import rendition_text
    run = _PageRun(strategy, page_deadline_seconds)
    try:
        body = rendition_text(data, rendition='pdf',
                              extractor=DocumentExtractor(run, max_input_bytes=max(1, len(data))))
    except (OcrRequired, PageDeadline, MemoryError):
        raise
    except Exception as error:  # an unopenable, encrypted or pageless document
        return Reading('error', type(error).__name__)
    pages = len(body.pages)
    if run.failed:
        return Reading('error', 'failed_pages', fields=dict(
            page_count=pages, failed_pages=run.failed,
            failed_page_errors=sorted(set(run.errors.values()))))
    return Reading('completed', text=body.text, page_offsets=page_offsets(body.pages),
                   ocr_pages=tuple(run.ocr), macos_build=macos_build() if run.ocr else None,
                   fields=dict(page_count=pages, **({'ocr_pages': len(run.ocr)} if run.ocr else {})))


def macos_build():
    """The host's macOS build (``kern.osversion``), which names what OCR ran on."""
    if platform.system() != 'Darwin':
        return None
    return subprocess.run(['/usr/sbin/sysctl', '-n', 'kern.osversion'], capture_output=True,
                          text=True, check=True, timeout=10).stdout.strip() or None


class EnvelopeRefused(Exception):
    """A WARC envelope or its payload encoding cannot be read; ``args[0]`` is the error type."""


def warc_payload(data, *, max_bytes):
    """Unwrap one WARC response member; its payload SHA-1 must equal the record's digest.

    A payload stored with HTTP ``Content-Encoding: gzip`` or ``deflate`` (zlib-wrapped, RFC 9110)
    is decoded, bounded by ``max_bytes``. Returns ``(payload bytes, envelope fields)``; raises
    :class:`EnvelopeRefused`.
    """
    from spicy_docs.sources.web_archive import WebArchiveError, read_warc_response
    try:
        response = read_warc_response(data)
    except WebArchiveError:
        raise EnvelopeRefused('warc_unreadable') from None
    payload = response.payload
    encoding = next((v.strip().lower() for k, v in response.publisher_headers if k.lower() == 'content-encoding'), '')
    if encoding in ('gzip', 'x-gzip', 'deflate'):
        try:
            payload = _decoded(payload, encoding, max_bytes)
        except (OSError, EOFError, zlib.error):
            raise EnvelopeRefused('payload_encoding') from None
        if payload is None:
            raise EnvelopeRefused('decoded_size_limit')
    return payload, dict(http_status=response.http_status, target_uri=response.target_uri)


def _decoded(payload, encoding, max_bytes):
    if encoding == 'deflate':
        stream = zlib.decompressobj()
        data = stream.decompress(payload, max_bytes + 1)
    else:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
            data = stream.read(max_bytes + 1)
    return None if len(data) > max_bytes else data


def derive(data, parser, *, strategy, page_deadline_seconds, sniff_format, max_bytes):
    """One body's reading under ``parser``. ``sniff_format(bytes)`` names a WARC payload's format."""
    if parser in MARKUP_RENDITIONS:
        return markup_text(data, parser)
    if parser == 'pdf_text':
        return pdf_text(data, strategy=strategy, page_deadline_seconds=page_deadline_seconds)
    if parser != 'warc':
        raise ValueError('Unsupported body-text parser')
    try:
        payload, envelope = warc_payload(data, max_bytes=max_bytes)
    except EnvelopeRefused as refused:
        return Reading('error', refused.args[0])
    kind = sniff_format(payload)
    inner = PAYLOAD_PARSERS.get(kind)
    if inner is None:
        return Reading('error', 'unsupported_payload', fields=dict(envelope, payload_format=kind))
    reading = derive(payload, inner, strategy=strategy, page_deadline_seconds=page_deadline_seconds,
                     sniff_format=sniff_format, max_bytes=max_bytes)
    return Reading(reading.status, reading.error_type, reading.text, reading.page_offsets, reading.ocr_pages,
                   reading.macos_build, dict(reading.fields, **envelope, payload_format=kind,
                        payload_sha256=hashlib.sha256(payload).hexdigest()))
