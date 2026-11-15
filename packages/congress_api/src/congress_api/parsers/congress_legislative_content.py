"""Select explicit Congress.gov legislative wrappers without changing their bytes.

The publisher emits USLM, generated HTML and preformatted text. Its generated
HTML omits some paragraph ends, so only the outer wrapper requires an explicit
end; SpicyDocs' tolerant event reader still owns syntax and byte coordinates.
The original embedded-bill policy remains available with its original meaning.
"""
from hashlib import sha256
import re
from urllib.parse import urlsplit

from spicy_docs.reading.html_index import HtmlIndexReader, children, descendants
from spicy_docs.reading.markup import HTML_VOID_TAGS, read_html_events, read_xml_events

from congress_api.parsers.congress_bill_content import HtmlContentSelection

POLICY = 'congress-gov-legislative-wrappers/002'
_LIMIT = 64 << 20
_NAMESPACE = 'http://schemas.gpo.gov/xml/uslm'
_PATH = re.compile(r'/bill/[1-9][0-9]*(?:st|nd|rd|th)-congress/'
                   r'(?:house-(?:bill|(?:concurrent-|joint-)?resolution)|senate-concurrent-resolution)/'
                   r'[1-9][0-9]*/text(?:/[a-z]+)?/?')
_READER = HtmlIndexReader('Congress.gov legislative text', ValueError,
                          max_bytes=_LIMIT, max_events=1_000_000)
_INERT = {'head', 'script', 'style', 'template', 'noscript'}


def _marked(attributes):
    return (attributes.get('id') in {'billTextUslm', 'billTextContainer'}
            or 'generated-html-container' in (attributes.get('class') or '').split())


def _closing_end(body, event):
    match = re.match(rb'</' + event.name.encode() + rb'\s*>', body[event.byte_start:], re.I)
    return None if match is None else event.byte_start + match.end()


def _wrappers(events):
    """Locate explicit wrapper ends in shared events, allowing omitted inner p ends.

    Matching an ancestor end discards unclosed descendants. Such an inferred end
    never completes a wrapper. Each event is pushed/popped once; no DOM repair or
    serialization occurs. Hidden/inert ancestry disqualifies a marked wrapper.
    """
    stack, opened, marked = [], {}, []
    document_closed = False
    for index, event in enumerate(events):
        if event.kind in {'start', 'empty'}:
            attrs = dict(event.attributes)
            blocked = ((stack and stack[-1]['blocked']) or event.name in _INERT
                       or 'hidden' in attrs or attrs.get('aria-hidden') == 'true')
            item = dict(start=index, end=None, blocked=bool(blocked))
            if _marked(attrs):
                item['duplicate_attributes'] = len(attrs) != len(event.attributes)
                marked.append(item)
            if event.kind == 'start' and event.name not in HTML_VOID_TAGS:
                opened.setdefault(event.name, []).append(len(stack))
                stack.append(item | dict(name=event.name, marked=item))
        elif event.kind == 'end' and opened.get(event.name):
            position = opened[event.name][-1]
            stack[position]['marked']['end'] = index
            if event.name == 'html':
                document_closed = True
            for item in reversed(stack[position:]):
                opened[item['name']].pop()
            del stack[position:]
    return marked, document_closed


def select_congress_legislative_content(body: bytes) -> HtmlContentSelection | None:
    """Select one complete, visible publisher wrapper; otherwise explain fallback."""
    if not any(marker in body for marker in (b'generated-html-container', b'billTextContainer', b'billTextUslm')):
        return None
    evidence = dict(policy=POLICY, outcome='fallback')

    def fallback(reason):
        return HtmlContentSelection(None, evidence | dict(reason=reason))

    try:
        head_tree = _READER.tree(body, max_bytes=_LIMIT, scopes=frozenset({'head'}))
        heads = children(head_tree, 'head')
        canonical = [node.attributes.get('href') for head in heads for node in descendants(head, 'link')
                     if 'canonical' in (node.attributes.get('rel') or '').split()]
        if len(heads) != 1 or len(canonical) != 1 or not canonical[0]:
            return fallback('missing_or_ambiguous_publisher')
        url = urlsplit(canonical[0])
        if (url.scheme != 'https' or url.netloc not in {'www.congress.gov', 'congress.gov'}
                or url.query or url.fragment or _PATH.fullmatch(url.path) is None):
            return fallback('unqualified_publisher')
        evidence['canonical_url'] = canonical[0]
        read = read_html_events(body, max_bytes=_LIMIT, max_events=1_000_000, max_depth=1_000_000)
        wrappers, document_closed = _wrappers(read.events)
        if len(wrappers) != 1:
            return fallback('missing_or_ambiguous_wrapper')
        wrapper = wrappers[0]
        if not document_closed or wrapper['end'] is None:
            return fallback('incomplete_wrapper_or_document')
        if wrapper['blocked'] or wrapper['duplicate_attributes']:
            return fallback('unqualified_wrapper')
        first, last = wrapper['start'], wrapper['end']
        start, end = read.events[first], read.events[last]
        attrs = dict(start.attributes)
        rendition = 'htm'
        if start.name == 'xml' and attrs.get('id') == 'billTextUslm' and 'generated-html-container' in (attrs.get('class') or '').split():
            # Ignore only wrapper whitespace and inert XML processing instructions
            # or comments. The exact root bytes must parse as one complete USLM
            # document; extra roots or substantive text cannot disappear here.
            def incidental(event):
                return event.kind in {'comment', 'pi'} or event.kind == 'text' and not (event.text or '').strip()
            first, last = first + 1, last - 1
            while first <= last and incidental(read.events[first]):
                first += 1
            while last >= first and incidental(read.events[last]):
                last -= 1
            if first > last:
                return fallback('incomplete_or_ambiguous_uslm')
            start, end = read.events[first], read.events[last]
            if start.kind != 'start' or end.kind != 'end' or start.name not in {'bill', 'plaw'} or end.name != start.name:
                return fallback('incomplete_or_ambiguous_uslm')
            rendition, family = 'uslm', 'uslm'
        elif start.name == 'div' and 'generated-html-container' in (attrs.get('class') or '').split():
            family = 'generated_html'
        elif start.name == 'pre' and attrs.get('id') == 'billTextContainer':
            family = 'preformatted'
        else:
            return fallback('unqualified_wrapper')
        byte_end = _closing_end(body, end)
        if byte_end is None:
            return fallback('unqualified_wrapper_end')
        selected = body[start.byte_start:byte_end]
        if rendition == 'uslm':
            parsed = read_xml_events(selected)
            if parsed.root_expanded_name not in {f'{{{_NAMESPACE}}}bill', f'{{{_NAMESPACE}}}pLaw'}:
                return fallback('unqualified_uslm_root')
            family = 'uslm_' + parsed.root_name
    except (ValueError, UnicodeError, RecursionError):
        return fallback('unqualified_markup')
    return HtmlContentSelection(selected, evidence | dict(outcome='selected', family=family,
        rendition=rendition, byte_start=start.byte_start, byte_end=byte_end,
        selected_bytes=len(selected), selected_sha256=sha256(selected).hexdigest()))
