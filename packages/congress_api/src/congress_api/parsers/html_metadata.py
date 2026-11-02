"""Read declared metadata from one retained HTML body, without fetching anything.

The reader is pure per (body, version): it takes no URL and records no timing, so
one result can be reused for every capture of a body. The exception is a result whose
``wall_clock_dependent`` is true: a deadline or memory failure depends on the machine,
so never reuse it as a complete reading. Page payloads and parser versions stay
untouched; a result is its own source record.

extruct is imported on call because it is a separate install (``html-metadata.in``),
not in every environment that imports this package.

Without a main thread there is no signal deadline, so ``format_timeout_seconds``
applies only on the main thread. Run this in a supervised worker's main thread.
"""
import json
import re
import signal
import threading
from collections import Counter, defaultdict
from contextlib import contextmanager
from hashlib import sha256
from importlib.metadata import version as installed_version
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
# Read in a libxml2 tree, which silently stops at depth 256. Mf2py parses separately;
# OpenGraph and Dublin Core read the head, which precedes any such depth.
_TRUNCATION_MARKERS = {
    'rdfa': _MARKERS['rdfa'],
    'microdata': re.compile(r'\bitem(?:scope|prop)\b', re.I),
    'json-ld': re.compile(r'ld\+json', re.I),
}


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

    A blank node's label is a digest of what it says and what refers to it, refined to
    a fixed point: O(rounds x output), with rounds bounded by the longest chain and the
    format deadline. Alike nodes share one label, so no tie is ever broken by input
    order. That merges only interchangeable nodes unless they form a cycle, which this
    refinement cannot tell apart, so a cycle fails the format.
    rdflib.compare was tried first: over 60 s on 200 identical pairs, against 0.5 s on a chain.
    """
    def blank(value):
        if isinstance(value, dict):
            found = {value['@id']} if str(value.get('@id', '')).startswith('_:') else set()
            return found.union(*map(blank, value.values()))
        return set().union(*map(blank, value)) if isinstance(value, list) else set()

    nodes = blank(items)
    edges = [(item.get('@id'), predicate, value['@id']) for item in items for predicate, values in item.items()
             if isinstance(values, list) for value in values if isinstance(value, dict) and value.get('@id') in nodes]
    colors = dict.fromkeys(nodes, '_:')
    for _ in range(len(nodes) + 1):
        said = dict.fromkeys(nodes, '')
        for item in items:
            if item.get('@id') in nodes:
                said[item['@id']] = _compact(_relabel(item, colors))
        heard = {node: [] for node in nodes}
        for subject, predicate, target in edges:
            heard[target].append(f'{predicate} {colors.get(subject, subject)}')
        refined = {node: '_:' + sha256(_compact([said[node], sorted(heard[node])]).encode()).hexdigest()[:32] for node in nodes}
        settled = len(set(refined.values())) == len(set(colors.values()))
        colors = refined
        if settled:
            break
    counts = Counter(colors.values())
    _refuse_tied_cycle({node for node in nodes if counts[colors[node]] > 1}, edges)
    return sorted((_relabel(item, colors) for item in items), key=lambda item: item.get('@id', ''))


def _refuse_tied_cycle(tied: set[str], edges: list) -> None:
    """Kahn's algorithm over the tied nodes; anything left over is on a cycle."""
    pending = Counter()
    outgoing = defaultdict(list)
    for subject, _, target in edges:
        if subject in tied and target in tied:
            pending[target] += 1
            outgoing[subject].append(target)
    ready = [node for node in tied if not pending[node]]
    for node in ready:
        for target in outgoing[node]:
            pending[target] -= 1
            if not pending[target]:
                ready.append(target)
    if len(ready) != len(tied):
        raise ValueError('RDFa blank nodes form a cycle of indistinguishable nodes')


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


def _transcode(body: bytes) -> tuple[str, str, bytes]:
    """Detected encoding, text and UTF-8 form. lxml rejects w3lib's names for UTF-16,
    so every parser reads the one transcoded form."""
    from w3lib.encoding import html_to_unicode

    try:
        encoding, decoded = html_to_unicode(None, body, default_encoding='utf-8')
    except Exception:  # a declared charset can name any Python codec: zlib, rot13, undefined
        encoding, decoded = 'utf-8', body.decode('utf-8', errors='replace')
    return encoding, decoded, decoded.encode('utf-8', errors='replace')


def _tree(utf8_body: bytes):
    """(tree or None, whether libxml2 stopped at its depth limit and dropped content)."""
    parser = dom.HTMLParser(encoding='utf-8')
    try:
        tree = dom.document_fromstring(utf8_body, parser=parser)
    except Exception:  # an empty or unparseable document; the formats report it separately
        return None, False
    return tree, any(error.type_name == 'ERR_RESOURCE_LIMIT' for error in parser.error_log)


def parse_document(body: bytes):
    """The reader's own DOM of a body, or None, so text selection sees the same document."""
    return _tree(_transcode(body)[2])[0]


def _head(tree) -> tuple[str | None, str | None, list[dict], list[dict]]:
    if tree is None:
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
                            declared_base=None, head_meta=[], head_links=[], document_truncated=False, extruct_version=None,
                            formats={name: FormatResult(status='skipped', skip_reason='non_html') for name in FORMATS})
    encoding, decoded, utf8_body = _transcode(body)
    tree, truncated = _tree(utf8_body)
    title, base, meta, links = _head(tree)
    results = {}
    for name in FORMATS:
        marker = _MARKERS.get(name)
        if name not in formats:
            results[name] = FormatResult(status='skipped', skip_reason='not_requested')
        elif marker is not None and not marker.search(decoded):
            results[name] = FormatResult(status='absent', basis='marker')
        elif truncated and name in _TRUNCATION_MARKERS and _TRUNCATION_MARKERS[name].search(decoded):
            results[name] = FormatResult(status='failed', error_type='document_too_deep',
                                         error_message='The parser dropped content past depth 256.')
        else:
            results[name] = _read_format(utf8_body, name, format_timeout_seconds)
    micro = results['microformat']
    if base is not None and micro.status == 'ok':  # mf2py resolves against <base> even with base_url=None
        micro.urls_resolved_against_base = True
    folded = (title or '').casefold()
    return HtmlMetadata(**common, encoding=encoding, document_kind='html',
                        error_title_hint=any(marker in folded for marker in ERROR_TITLE_MARKERS),
                        title=title, declared_base=base, formats=results, head_meta=meta, head_links=links,
                        document_truncated=truncated, extruct_version=installed_version('extruct'))


def page_is_substantive(metadata: HtmlMetadata, http_status: int) -> bool:
    """Extraction values never admit a page; rich metadata on an error page is still an error page."""
    return metadata.document_kind == 'html' and not metadata.error_title_hint and 200 <= http_status < 300


_OPENGRAPH_FACTS = {'article:published_time': 'published_time', 'article:modified_time': 'modified_time',
                    'og:description': 'description', 'article:section': 'section', 'og:url': 'declared_url'}
_JSON_LD_FACTS = {'datePublished': 'published_time', 'dateModified': 'modified_time', 'description': 'description',
                  'articleSection': 'section', '@type': 'declared_type', 'author': 'person_card'}


def _json_ld_facts(node: dict, path: str):
    for key, field in _JSON_LD_FACTS.items():
        value = node.get(key)
        if isinstance(value, list):
            yield from (PageFact(field, item, 'json-ld', f'{path}/{key}/{index}') for index, item in enumerate(value))
        elif value is not None:
            yield PageFact(field, value, 'json-ld', f'{path}/{key}')


def page_facts(metadata: HtmlMetadata) -> tuple[PageFact, ...]:
    """Every declared value of the field vocabulary, unselected, each with its JSON Pointer.

    The one authority for field meanings, so the retained store and publication read
    the same facts. JSON-LD is read at its top level and in @graph, not nested deeper.
    """
    facts = []
    for index, item in enumerate(metadata.formats['json-ld'].items):
        path = f'/formats/json-ld/items/{index}'
        if isinstance(item, dict):
            facts += _json_ld_facts(item, path)
            graph = item.get('@graph')
            for position, node in enumerate(graph if isinstance(graph, list) else ()):
                if isinstance(node, dict):
                    facts += _json_ld_facts(node, f'{path}/@graph/{position}')
    for index, item in enumerate(metadata.formats['opengraph'].items):
        for position, (name, value) in enumerate(item.get('properties', ())):
            if name in _OPENGRAPH_FACTS:
                facts.append(PageFact(_OPENGRAPH_FACTS[name], value, 'opengraph', f'/formats/opengraph/items/{index}/properties/{position}/1'))
    for index, meta in enumerate(metadata.head_meta):
        if meta.get('name', '').casefold() == 'description' and 'content' in meta:
            facts.append(PageFact('description', meta['content'], 'head_meta', f'/head_meta/{index}/content'))
    for index, link in enumerate(metadata.head_links):
        if 'canonical' in link['rel'].casefold().split() and 'href' in link:
            facts.append(PageFact('declared_url', link['href'], 'head_links', f'/head_links/{index}/href'))
    for index, item in enumerate(metadata.formats['microformat'].items):
        if 'h-card' in item.get('type', ()):
            facts.append(PageFact('person_card', item, 'microformat', f'/formats/microformat/items/{index}'))
    return tuple(facts)
