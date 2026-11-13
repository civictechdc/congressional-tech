"""Body text of one decoded body, for the body-text parsers (data model §6.2, §6.6).

Pure derivations over bytes already read: no storage, catalog or provenance. The text
rules are spicy-docs': its markup reader for ``html_text`` and ``xml_text``, its
``DocumentExtractor`` plus ``normalize_gpo_pages`` for ``pdf_text``, and its WARC reader for
``warc``, whose payload the caller sniffs and routes back here. What this module adds is the
page rule's injection point and the bounds around it:

- **Page rule.** ``pdf_text`` takes a :class:`PageRule`: a spicy-docs ``PageStrategy``
  (``extract(page) -> PageContent``) and the reader that renders for it. The declared rule is
  :func:`page_rule`, spicy-docs' ``NativeOrOcr`` judging each page's native text as GPO
  normalization leaves it: keep a sane native layer, else recognize the page whole. A page is
  OCR'd when its content carries a ``native-text-replaced`` issue (or any observation but
  ``native``). :func:`apple_vision` is the declared engine; the default, :func:`native_only`,
  has none: a page the rule sends to OCR raises :class:`OcrRequired`, so a host without Vision
  leaves that body on the work list (§6.6: the version names its OCR engine).
- **Failed pages.** A page whose extraction fails is recorded in ``failed_pages`` and the
  reading is an ``error`` with no text: a partial text is never passed as complete.
- **Deadlines.** A per-page user-CPU deadline runs inside the worker (``ITIMER_VIRTUAL`` /
  ``SIGVTALRM``, main thread only), so stopping or sleeping does not spend it; it can interrupt
  Python code between bytecodes, not one long native call, which the supervisor's document
  deadline bounds instead.

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
import resource
import signal
import subprocess
import threading
import traceback
import zlib

from congress_api.parsers.archive_readings import fingerprint

TEXT_HEAD_BYTES = 2048
# The declared page rule (reading_versions declares the same): NativeOrOcr's control_characters
# garble rule and image test, OCR_MIN_CHARS, Apple Vision in OCR_BANDS strips at OCR_DPI.
OCR_MIN_CHARS = 50
OCR_BANDS = 3
OCR_DPI = 200
REPLACED_ISSUE = 'native-text-replaced'
MARKUP_RENDITIONS = {'html_text': 'htm', 'xml_text': 'xml'}
PAYLOAD_PARSERS = {'pdf': 'pdf_text', 'html': 'html_text', 'xml': 'xml_text'}
DEFAULT_STRATEGY = 'congress_api.parsers.body_text:native_only'
VISION_STRATEGY = 'congress_api.parsers.body_text:apple_vision'


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
    diagnostic: str | None = None

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
        return Reading('error', type(error).__name__, diagnostic=traceback.format_exc(limit=8))
    return Reading('completed', text=text, page_offsets=(0,), fields=dict(page_count=1))


@dataclass(frozen=True)
class PageRule:
    """The page strategy and the reader that renders for it (None: DocumentExtractor's default)."""
    strategy: object
    reader: object = None


class NoEngine:
    """The image backend of a host without the declared OCR engine: any page sent to it waits."""

    def recognize(self, image):
        raise OcrRequired('page needs OCR and this host has no engine')


def gpo_page(text):
    """One page's native text as GPO normalization leaves it: what the rule counts and checks.

    A GPO hearing page whose body is an inserted scan keeps only its ``VerDate`` footer, 50 or more
    characters raw, which normalization strips (plan §1: raw counts missed 78% of such pages).
    ``normalize_gpo_pages`` takes a document's pages, so one page goes in as a document of one.
    """
    from spicy_docs.extraction.gpo_normalize import normalize_gpo_pages
    return normalize_gpo_pages([text])[0][0]


def page_rule(backend, reader=None):
    """The declared routing over ``backend``: spicy-docs ``NativeOrOcr`` on GPO-normalized text."""
    from spicy_docs.extraction import NativeOrOcr
    return PageRule(NativeOrOcr(backend, min_chars=OCR_MIN_CHARS, normalize=gpo_page), reader)


def native_only():
    """The default page rule: the declared routing with no OCR engine."""
    return page_rule(NoEngine())


def apple_vision():
    """The declared engine: Apple Vision, accurate, correction off, three bands, raw RGB at 200 dpi.

    Builds Vision's request now, so a host without it refuses here, before any body is read,
    rather than failing every OCR page.
    """
    from spicy_docs.extraction import DefaultReader
    from spicy_docs.extraction.ocr import AppleVision
    backend = AppleVision(recognition_level='accurate', language_correction=False, bands=OCR_BANDS)
    backend.require_reproducible_identity()
    return page_rule(backend, DefaultReader(dpi=OCR_DPI, raw_rgb=True))


def load_page_rule(spec):
    """Construct the page rule a payload names as ``module:callable`` (no arguments)."""
    module, name = spec.split(':', 1)
    made = getattr(importlib.import_module(module), name)()
    return made if isinstance(made, PageRule) else PageRule(made)


@contextmanager
def page_deadline(seconds, page_number):
    """Raise :class:`PageDeadline` in this thread after ``seconds`` of user CPU; off outside the main thread.

    ``ITIMER_VIRTUAL`` measures process user-mode CPU time only, so a stop (``SIGSTOP``) or sleep
    never spends the deadline, while ``ParserWorker``'s outer 1,800 s ``time.monotonic()`` deadline
    bounds wall-clock and XPC/Vision stalls. Any previous virtual timer (less user CPU spent here)
    and handler are always restored.
    """
    if not seconds or threading.current_thread() is not threading.main_thread():
        yield
        return
    def expire(*_):
        raise PageDeadline(page_number)
    # ITIMER_VIRTUAL counts process user-mode CPU; ParserWorker's 1,800s time.monotonic() bounds wall/XPC stalls.
    started_utime = resource.getrusage(resource.RUSAGE_SELF).ru_utime
    previous_handler = signal.signal(signal.SIGVTALRM, expire)
    previous_timer = (0.0, 0.0)
    try:
        previous_timer = signal.setitimer(signal.ITIMER_VIRTUAL, seconds)
        yield
    finally:
        signal.signal(signal.SIGVTALRM, signal.SIG_IGN)
        signal.setitimer(signal.ITIMER_VIRTUAL, 0)
        signal.signal(signal.SIGVTALRM, previous_handler)
        if any(previous_timer):
            spent = max(0.0, resource.getrusage(resource.RUSAGE_SELF).ru_utime - started_utime)
            delay = max(0.001, previous_timer[0] - spent) if previous_timer[0] > 0 else 0.0
            if delay > 0 or previous_timer[1] > 0:
                signal.setitimer(signal.ITIMER_VIRTUAL, delay or previous_timer[1], previous_timer[1])


class _PageRun:
    """Wrap a strategy: time each page, record OCR'd and failed pages, keep going after a failure.

    Keeps page numbers and the OCR build only; each page's content (a raw-RGB raster is about
    11 MB) goes straight back to the extractor and is not held.
    """

    def __init__(self, strategy, deadline_seconds):
        self.strategy, self.deadline = strategy, deadline_seconds
        self.ocr, self.failed, self.errors, self.builds = [], [], {}, set()
        self.diagnostics = {}

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
            self.diagnostics[page.number] = traceback.format_exc(limit=8)
            return PageContent((), ())
        replaced = [o for o in content.observations if o.id != 'native'
                    or any(issue.code == REPLACED_ISSUE for issue in o.issues)]
        if replaced:
            self.ocr.append(page.number)
            self.builds.update(o.configuration.get('macos_build') for o in replaced
                               if isinstance(o.configuration, dict) and o.configuration.get('macos_build'))
        return content


def pdf_text(data, *, strategy, page_deadline_seconds):
    """``pdf_text``: one open of the PDF, each page through the rule, then GPO normalization.

    ``strategy`` is a :class:`PageRule` or a bare page strategy (rendered by the default reader).
    Raises :class:`OcrRequired` or :class:`PageDeadline`; every other failure is a reading.
    """
    from spicy_docs.extraction import DocumentExtractor
    from spicy_docs.extraction.body_text import rendition_text
    rule = strategy if isinstance(strategy, PageRule) else PageRule(strategy)
    run = _PageRun(rule.strategy, page_deadline_seconds)
    try:
        body = rendition_text(data, rendition='pdf', extractor=DocumentExtractor(
            run, reader=rule.reader, max_input_bytes=max(1, len(data))))
    except (OcrRequired, PageDeadline, MemoryError):
        raise
    except Exception as error:  # an unopenable, encrypted or pageless document
        return Reading('error', type(error).__name__, diagnostic=traceback.format_exc(limit=8))
    pages = len(body.pages)
    if run.failed:
        return Reading('error', 'failed_pages', fields=dict(
            page_count=pages, failed_pages=run.failed,
            failed_page_errors=sorted(set(run.errors.values()))), diagnostic='\n'.join(
                f'Page {page}: {error}' for page, error in run.diagnostics.items()))
    if len(run.builds) > 1:
        raise ValueError('OCR in one document ran on more than one macOS build')
    # The build the OCR backend states (AppleVision's configuration), else this host's.
    build = (next(iter(run.builds)) if run.builds else macos_build()) if run.ocr else None
    return Reading('completed', text=body.text, page_offsets=page_offsets(body.pages),
                   ocr_pages=tuple(run.ocr), macos_build=build,
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
        data = stream.decompress(payload, 0 if max_bytes is None else max_bytes + 1)
    else:
        with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
            data = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
    return None if max_bytes is not None and len(data) > max_bytes else data


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
                        payload_sha256=hashlib.sha256(payload).hexdigest()), reading.diagnostic)
