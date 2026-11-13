"""Bounded source-role observations, separate from extraction and acceptance.

Only narrow publisher response structures receive a role. Everything else stays
unassessed: an absent match never certifies a document, and these observations do
not discard a capture, select text, or request a replacement. Spicy-docs owns the
markup syntax, safety limits and original-byte event positions.
"""
from dataclasses import dataclass
from hashlib import sha256

from spicy_docs.extraction.body_text import HTM_BLOCK_ELEMENTS
from spicy_docs.reading.markup import HTML_VOID_TAGS, MarkupReadError, read_html_events, read_xml_events

POLICY_VERSION = 'ct-response-roles-v1'
MAX_BYTES = 1 << 20
MAX_EVIDENCE_FIELDS = 512
MAX_EVIDENCE_TEXT_CHARS = 64 << 10
_HEADINGS = {'h1', 'h2', 'h3'}
_HIDDEN = {'script', 'style', 'template', 'noscript'}


@dataclass(frozen=True)
class ResponseRole:
    body_sha256: str
    role: str
    reason: str
    policy_version: str
    evidence: tuple[dict, ...] = ()


def _normal(text):
    return ' '.join(text.split()).casefold()


class _EvidenceLimit(ValueError):
    """A role observation must stay bounded even for malformed nested headings."""


def _html_fields(events):
    stack, fields, visible = [], [], []
    evidence_chars = 0

    def append_active(value):
        nonlocal evidence_chars
        active = [item for _, item in stack if item is not None]
        evidence_chars += len(value) * len(active)
        if evidence_chars > MAX_EVIDENCE_TEXT_CHARS:
            raise _EvidenceLimit('title and heading text exceeds the evidence bound')
        for item in active:
            item['parts'].append(value)

    for event in events:
        if event.kind in {'start', 'empty', 'end'} and event.name in HTM_BLOCK_ELEMENTS:
            visible.append('\n')
        if event.kind in {'start', 'empty'}:
            if event.name == 'br':
                append_active('\n')
            item = None
            if event.name in {'title', *_HEADINGS}:
                if len(fields) >= MAX_EVIDENCE_FIELDS:
                    raise _EvidenceLimit('title and heading count exceeds the evidence bound')
                item = dict(field=event.name, byte_start=event.byte_start, byte_end=None, parts=[])
                fields.append(item)
            if event.kind == 'start' and event.name not in HTML_VOID_TAGS:
                stack.append((event.name, item))
        elif event.kind == 'end':
            names = [name for name, _ in stack]
            if event.name in names:
                close_at = len(names) - 1 - names[::-1].index(event.name)
                # Closing an ancestor also ends every heading inside it. An
                # unclosed heading cannot accumulate later sibling content.
                for _, item in stack[close_at:]:
                    if item is not None:
                        item['byte_end'] = event.byte_start
                del stack[close_at:]
        elif event.kind == 'text' and not (_HIDDEN & {name for name, _ in stack}):
            append_active(event.text or '')
            if not any(name == 'head' for name, _ in stack):
                visible.append(event.text or '')
    for item in fields:
        item['text'] = _normal(''.join(item.pop('parts')))
    # Character references may be separate text events inside one word or URL.
    # Only the shared block-element policy contributes separators.
    return fields, _normal(''.join(visible))


def assess_response(body: bytes, *, format: str, max_bytes=MAX_BYTES):
    """Observe a complete bounded byte string; no network, OCR, or state writes.

    A zero-byte response is a byte fact, not a valid-empty document verdict.
    Unsupported, over-bound, malformed and undecodable inputs remain unassessed.
    Callers retain response/capture history and decide whether any later action
    is justified. Large feeds use their dedicated structured source reader.
    """
    if not isinstance(body, bytes):
        raise TypeError('Response assessment requires original bytes')
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 0 < max_bytes <= MAX_BYTES:
        raise ValueError('max_bytes must be positive and no greater than MAX_BYTES')
    digest = sha256(body).hexdigest()

    def result(role, reason, evidence=()):
        return ResponseRole(digest, role, reason, POLICY_VERSION, tuple(evidence))

    if not body:
        return result('empty_response', 'zero_payload_bytes')
    if len(body) > max_bytes:
        return result('unassessed', 'source_exceeds_assessment_bound')
    if format not in {'html', 'xml'}:
        return result('unassessed', 'unsupported_source_format')
    try:
        read = (read_html_events if format == 'html' else read_xml_events)(
            body, max_bytes=max_bytes, max_events=100_000, max_depth=64)
    except (MarkupReadError, UnicodeError) as error:
        return result('unassessed', 'markup_reader_refused', [dict(error_type=type(error).__name__)])
    if format == 'xml':
        if read.root_expanded_name == '{http://www.w3.org/2005/Atom}feed':
            return result('feed', 'atom_root', [dict(root=read.root_expanded_name)])
        if read.root_expanded_name != 'Error':
            return result('unassessed', 'no_qualified_response_structure', [dict(root=read.root_expanded_name)])
        stack, children = [], []
        nested = mixed_root = foreign_child = False
        for event in read.events:
            if event.kind in {'start', 'empty'}:
                scope = (stack[-1][0] if stack else {}) | dict(event.namespace_declarations)
                nested |= len(stack) > 1
                child = None
                if len(stack) == 1:
                    child = dict(field=event.name, byte_start=event.byte_start, parts=[])
                    prefix, _, local = (event.name or '').rpartition(':')
                    namespace = scope.get(prefix, '' if not prefix else None)
                    if namespace != '':
                        foreign_child = True
                        child['expanded_name'] = f'{{{namespace}}}{local}'
                    children.append(child)
                if event.kind == 'start':
                    stack.append((scope, child))
            elif event.kind == 'end':
                if stack:
                    stack.pop()
            elif event.kind == 'text':
                if len(stack) == 1 and (event.text or '').strip():
                    mixed_root = True
                    children.append(dict(field='#root_text', byte_start=event.byte_start, parts=[event.text]))
                elif len(stack) >= 2:
                    stack[1][1]['parts'].append(event.text or '')
        for item in children:
            item['text'] = ''.join(item.pop('parts')).strip()
        codes = [item['text'] for item in children if item['field'] == 'Code']
        # These are root-level storage responses, not phrase hits inside a report.
        allowed = {'Code', 'Message', 'BucketName', 'RequestId', 'HostId', 'Key', 'Resource', 'Region', 'Endpoint'}
        if (not nested and not mixed_root and not foreign_child and {item['field'] for item in children} <= allowed
                and len(codes) == 1 and codes[0] in {'NoSuchKey', 'AccessDenied'} and any(
                    item['field'] == 'RequestId' and item['text'] for item in children)):
            return result('error_response', 'storage_' + codes[0], children)
        return result('unassessed', 'unqualified_error_structure', children)

    try:
        fields, visible = _html_fields(read.events)
    except _EvidenceLimit as error:
        return result('unassessed', 'evidence_exceeds_assessment_bound', [dict(error=str(error))])
    titles = [item['text'] for item in fields if item['field'] == 'title']
    headings = {item['text'] for item in fields if item['field'] in _HEADINGS}
    if len(titles) != 1:
        return result('unassessed', 'missing_or_ambiguous_title', fields)
    title = titles[0]
    reason = None
    if (title == 'error | house committee on natural resources' and 'page not found' in headings
            and "either not here or has been moved" in visible):
        reason = 'natural_resources_not_found'
    elif (title == 'access denied' and 'access denied' in headings
          and "you don't have permission to access" in visible and 'https://errors.edgesuite.net/' in visible):
        reason = 'edge_access_denied'
    elif (title.endswith('| 522: connection timed out') and 'connection timed out error code 522' in headings
          and 'cloudflare' in visible):
        reason = 'cloudflare_origin_timeout'
    elif (title == 'attention required! | cloudflare' and 'sorry, you have been blocked' in headings
          and 'why have i been blocked?' in headings):
        reason = 'cloudflare_browser_block'
    elif (title == 'u.s. senate: site under maintenance'
          and 'website temporarily unavailable due to maintenance. normal service will return soon.' in headings
          and 'normal service will return soon.' in visible):
        return result('wait_response', 'senate_maintenance', fields)
    elif (title == 'page not found | urban institute'
          and 'we searched high and low but couldn’t find what you’re looking for.' in visible):
        reason = 'urban_institute_not_found'
    if reason:
        return result('error_response', reason, fields)
    return result('unassessed', 'no_qualified_response_structure', fields)
