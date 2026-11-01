"""Read declared metadata from one retained HTML body, without fetching anything.

The reader is pure per (body, version): it takes no URL and records no timing, so
one result can be reused for every capture of a body. Page payloads and parser
versions stay untouched; a result is its own source record.

extruct is imported on call because it lives in the hash-pinned sidecar
(``html-metadata.lock.txt``), not in every environment that imports this package.

Without a main thread there is no signal deadline, so ``format_timeout_seconds``
applies only on the main thread. Run this in a supervised worker's main thread.
"""
import json
import re
import signal
import threading
from contextlib import contextmanager
from hashlib import sha256
from typing import Any

from lxml import html as dom

from congress_api.models.html_metadata import METADATA_SCHEMA, FormatResult, HtmlMetadata, PageFact

FORMATS = ('json-ld', 'opengraph', 'dublincore', 'microdata', 'microformat', 'rdfa')
FORMAT_TIMEOUT_SECONDS = 10.0

# Lowercased. A superset of retention/capture_inspection.py's title markers, which
# parsers may not import; a test holds the two together.
ERROR_TITLE_MARKERS = (
    'just a moment', 'access denied', 'attention required', 'page not found', 'file not found',
    '404 not found', '403 forbidden', '500 internal server error', 'internal server error',
    '502 bad gateway', '503 service unavailable', 'service unavailable', 'request rejected',
)

# mf2py roots beyond its h-* syntax. A test holds this as a superset of its rule files.
MICROFORMAT_LEGACY_ROOTS = ('adr', 'geo', 'hentry', 'hfeed', 'hnews', 'hproduct', 'hrecipe', 'hresume',
                            'hreview', 'hreview-aggregate', 'vcard', 'vevent', 'xoxo')
# Deliberately not scoped to class= or to a tag: that narrower form missed real bodies.
_MARKERS = {
    'microformat': re.compile(r'(?<![\w-])(?:h-[a-z0-9]+(?:-[a-z0-9]+)*|'
                              + '|'.join(map(re.escape, MICROFORMAT_LEGACY_ROOTS)) + r')(?![\w-])'),
    'rdfa': re.compile(r'(?<![\w-])(?:about|property|resource|typeof|vocab|prefix|rel|rev|datatype|inlist)\s*=', re.I),
}
_HTML_START = re.compile(rb'<(?:!doctype\s+html|html|head|body|title|meta|div|p|script)\b', re.I)
_MESSAGE_LIMIT = 500
_RDFA_ROUNDS = 8


class _FormatDeadline(BaseException):
    """A BaseException, so a library's ``except Exception`` cannot swallow the deadline."""


def is_html(body: bytes) -> bool:
    sample = body[:65536]
    if sample.startswith((b'\xff\xfe', b'\xfe\xff')):
        sample = sample.decode('utf-16', errors='replace').encode('utf-8')
    prefix = sample.lstrip(b'\xef\xbb\xbf\x00\t\n\r ')
    return prefix.startswith(b'<') and bool(_HTML_START.search(sample))


@contextmanager
def _deadline(seconds: float):
    if threading.current_thread() is not threading.main_thread() or not seconds:
        yield
        return
    def expired(signum, frame):
        raise _FormatDeadline()
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _relabel(value: Any, labels: dict[str, str]) -> Any:
    """Copy one RDFa value with blank-node references replaced and multi-values sorted."""
    if isinstance(value, dict):
        return {key: labels.get(item, item) if key == '@id' else _relabel(item, labels) for key, item in value.items()}
    if isinstance(value, list):
        return sorted((_relabel(item, labels) for item in value), key=_compact)
    return value


def _compact(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def _canonical_rdfa(items: list) -> list:
    """Remove pyRdfa's run-to-run noise: random blank-node IDs and hash-seeded order.

    Blank nodes are labelled by what they say and what refers to them, refined over a
    bounded number of rounds (O(rounds x output)). Nodes still alike after that are
    interchangeable, so the order among them cannot change the serialized result.
    """
    def blank(value):
        if isinstance(value, dict):
            found = {value['@id']} if str(value.get('@id', '')).startswith('_:') else set()
            return found.union(*map(blank, value.values()))
        return set().union(*map(blank, value)) if isinstance(value, list) else set()

    nodes = blank(items)
    colors = {node: '_:' for node in nodes}
    for _ in range(_RDFA_ROUNDS if nodes else 0):
        said = dict.fromkeys(nodes, '')
        heard = {node: [] for node in nodes}
        for item in items:
            subject = item.get('@id')
            if subject in nodes:
                said[subject] = _compact(_relabel(item, colors))
            for predicate, values in item.items():
                for value in values if isinstance(values, list) else ():
                    target = value.get('@id') if isinstance(value, dict) else None
                    if target in nodes:
                        heard[target].append(f'{predicate} {colors.get(subject, subject)}')
        refined = {node: '_:' + sha256(_compact([said[node], sorted(heard[node])]).encode()).hexdigest() for node in nodes}
        settled = len(set(refined.values())) == len(set(colors.values()))
        colors = refined
        if settled:
            break
    labels = {node: f'_:b{index}' for index, node in enumerate(sorted(nodes, key=lambda node: (colors[node], node)))}
    return sorted((_relabel(item, labels) for item in items), key=lambda item: item.get('@id', ''))


def _meaningful(name: str, items: list) -> bool:
    if name == 'dublincore':  # extruct always yields one wrapper, usually empty
        return any(item.get('elements') or item.get('terms') for item in items)
    return bool(items)


def _read_format(utf8_body: bytes, name: str, timeout: float) -> FormatResult:
    import extruct

    try:
        with _deadline(timeout):
            # One call per format isolates failures. base_url=None keeps URLs literal.
            items = extruct.extract(utf8_body, base_url=None, encoding='utf-8', syntaxes=[name], errors='strict')[name]
            if name == 'rdfa':
                items = _canonical_rdfa(items)
        if not _meaningful(name, items):
            return FormatResult(status='absent', basis='extractor', items=[])
        # A round trip yields plain JSON values; unserializable output fails here, in this format only.
        return FormatResult.model_validate(FormatResult(status='ok', basis='extractor', items=items).source_dict())
    except _FormatDeadline:
        return FormatResult(status='failed', error_type='format_timeout',
                            error_message=f'exceeded {timeout} seconds')
    except Exception as error:  # includes RecursionError and MemoryError; never becomes empty
        return FormatResult(status='failed', error_type=type(error).__name__,
                            error_message=str(error)[:_MESSAGE_LIMIT])


def _head(utf8_body: bytes) -> tuple[str | None, str | None, list[dict], list[dict]]:
    try:
        tree = dom.document_fromstring(utf8_body, parser=dom.HTMLParser(encoding='utf-8'))
    except Exception:  # an empty or unparseable document has no head tags; formats report it separately
        return None, None, [], []
    title = next((node.text_content().strip() for node in tree.xpath('//title')), None)
    base = next(iter(tree.xpath('//base/@href')), None)
    return (title or None, str(base) if base is not None else None,
            [dict(node.attrib) for node in tree.xpath('//meta')],
            [dict(node.attrib) for node in tree.xpath('//link[@rel]')])


def read_html_metadata(body: bytes, *, formats: tuple[str, ...] = FORMATS,
                       format_timeout_seconds: float = FORMAT_TIMEOUT_SECONDS) -> HtmlMetadata:
    """Run the requested formats over one body; a format's failure never affects another."""
    common = dict(schema_version=METADATA_SCHEMA, body_sha256=sha256(body).hexdigest(), body_bytes=len(body))
    if not is_html(body):
        return HtmlMetadata(**common, encoding=None, document_kind='non_html', error_title_hint=False, title=None,
                            declared_base=None, head_meta=[], head_links=[],
                            formats={name: FormatResult(status='skipped', skip_reason='non_html') for name in FORMATS})
    from w3lib.encoding import html_to_unicode

    encoding, decoded = html_to_unicode(None, body, default_encoding='utf-8')
    # lxml rejects w3lib's names for UTF-16, so every parser reads one transcoded form.
    utf8_body = decoded.encode('utf-8', errors='replace')
    title, base, meta, links = _head(utf8_body)
    results = {}
    for name in FORMATS:
        marker = _MARKERS.get(name)
        if name not in formats:
            results[name] = FormatResult(status='skipped', skip_reason='not_requested')
        elif marker is not None and not marker.search(decoded):
            results[name] = FormatResult(status='absent', basis='marker')
        else:
            results[name] = _read_format(utf8_body, name, format_timeout_seconds)
    micro = results['microformat']
    if base is not None and micro.status == 'ok':  # mf2py resolves against <base> even with base_url=None
        micro.urls_resolved_against_base = True
    folded = (title or '').casefold()
    return HtmlMetadata(**common, encoding=encoding, document_kind='html',
                        error_title_hint=any(marker in folded for marker in ERROR_TITLE_MARKERS),
                        title=title, declared_base=base, formats=results, head_meta=meta, head_links=links)


def page_is_substantive(metadata: HtmlMetadata, http_status: int) -> bool:
    """Extraction values never admit a page; rich metadata on an error page is still an error page."""
    return metadata.document_kind == 'html' and not metadata.error_title_hint and 200 <= http_status < 300
