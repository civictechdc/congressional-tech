"""Interpret selected retained records and PDF covers without changing source locators.

The caller supplies body reading and filename interpretation. Publisher filenames
are recovered only by forward-matching known URLs through the legacy cache key.
"""
from collections import defaultdict
import gzip
from hashlib import sha256
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import ParseError
from zipfile import is_zipfile

from congress_api.parsers.house_xml import parse_house_meeting, parse_house_witnesses
from congress_api.parsers.document_cover import COVER_FIELDS, document_cover
from congress_api.parsers import pdf_tools
from congress_api.parsers.xml import parse_xml, xml_element


FIELDS = frozenset({
    'record_role', 'body_format', 'content_document_kind', 'content_citation', 'cache_marker_state',
    'attempted_url', 'recovered_filename', 'recovered_source_url',
    'source_record_document_url',
    'content_xml_root', 'content_amendment_type', 'content_amendment_stage',
    'content_amendment_degree', 'content_legis_num', *COVER_FIELDS,
})
ENCODED_NAME = re.compile(r'house_\d+_documents_')
BODY_FIELDS = FIELDS - {'recovered_filename', 'recovered_source_url'} | {
    'source_record_type', 'source_record_identifier',
}


def evidence_fingerprint():
    """Identify the current readers for processing provenance, not cache expiry."""
    import congress_api.models.house as models
    import congress_api.models.xml as xml_models
    import congress_api.parsers.house_xml as house_xml
    import congress_api.parsers.document_cover as document_cover
    import congress_api.parsers.xml as xml
    digest = sha256()
    for path in (__file__, models.__file__, xml_models.__file__, house_xml.__file__, xml.__file__, document_cover.__file__, pdf_tools.__file__):
        digest.update(Path(path).read_bytes())
    for tool, identity in sorted(pdf_tools.reader_versions().items()):
        digest.update(f'{tool}={identity}\n'.encode())
    return digest.hexdigest()


def body_evidence_key(row):
    if not row.get('body_key'):
        return None
    if row.get('cache_marker_state') and row['cache_marker_state'] != ['unread']:
        return ('marker', row['body_key'])
    if (row.get('body_format') == ['xml']
            and (row.get('source_record_type') in (['committee-meeting'], ['witness-list'])
                 or row.get('content_xml_root') == ['amendment-doc'])):
        return ('xml', row['body_key'])
    if row.get('body_format') in (['pdf'], ['html'], ['zip']):
        return ('document', row['body_key'])
    return None


def cached_body_fields(row, key):
    if key[0] == 'document':
        fields = {'body_format', *COVER_FIELDS}
        if row.get('source_record_type') == ['error-page']:
            fields |= {'record_role', 'source_record_type'}
    else:
        fields = BODY_FIELDS
    cached = {k: v for k, v in row.items() if k in fields and v}
    if key[0] == 'xml' and cached.get('record_role') == ['error-response']:
        # XML meaning follows bytes; a failed retrieval belongs to its capture.
        cached['record_role'] = ['source-record' if cached.get('source_record_type') == ['committee-meeting']
                                 else 'document']
    return cached


def response_failed(row):
    """Whether the retained response evidence establishes a failed capture.

    Flat lists can contain both a successful capture and an older failure.
    Mixed values therefore do not establish failure. A validated usable result
    outweighs status history, but not explicit incomplete bytes or a failed
    content inspection. Missing/deferred validation is never itself failure.
    """
    usable = set(row.get('response_usable') or [])
    complete = set(row.get('response_body_complete') or [])
    if usable == {'false'} or complete == {'false'}:
        return True
    outcomes = set(row.get('capture_outcome') or [])
    failures = {'challenge', 'incomplete', 'error', 'request_failed',
                'http_error', 'invalid_document', 'empty', 'parse_failed'}
    if outcomes and outcomes <= failures:
        return True
    if 'true' in usable:
        return False
    statuses = {int(value) for value in row.get('http_status') or []
                if re.fullmatch(r'[0-9]{3}', str(value))}
    if statuses and not any(200 <= status < 300 for status in statuses):
        return True
    return False


def apply_response_role(row):
    """Recompute capture-derived failure without replacing proven source/body roles."""
    if (not row.get('body_key') and row.get('source_probe_status')
            and 'xml' not in row['source_probe_status']):
        row['record_role'] = ['capture-state']
        return
    if row.get('record_role') in (['source-record'], ['capture-state']):
        return
    if row.get('source_record_type') == ['error-page']:
        row['record_role'] = ['error-response']
    else:
        row['record_role'] = ['error-response' if response_failed(row) else 'document']


def legacy_house_cache_name(url):
    """Exact historical witness-PDF cache key; lossy and never reversible alone."""
    return re.sub(r'\W+', '_', url.split('/meeting/')[-1])


def read_retained_body(root, key, *, read_compressed=None, limit=16 * 1024 * 1024):
    """Read bounded content-addressed evidence; missing/oversize bodies abstain."""
    match = re.fullmatch(r'bodies/sha256/([a-f0-9]{2})/([a-f0-9]{64})\.gz', key or '')
    if not match or match[1] != match[2][:2]:
        return None
    try:
        if read_compressed is None:
            source = gzip.open(root / key, 'rb')
        else:
            payload = read_compressed(key)
            if payload is None:
                return None
            source = gzip.GzipFile(fileobj=BytesIO(payload))
        with source:
            data = source.read(limit + 1)
    except FileNotFoundError:
        return None
    if len(data) > limit:
        return None
    if sha256(data).hexdigest() != match[2]:
        raise ValueError(f'Retained body digest mismatch: {key}')
    return data


class _PageTitle(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_title = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == 'title':
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.parts.append(data)


def house_record(data):
    """Read supported House XML structures; other roots remain uninterpreted."""
    if data is None:
        return {}
    try:
        root = parse_xml(data)
        if (root.tag == 'amendment-doc' and root.get('amend-type') in {'house-amendment', 'senate-amendment'}
                and root.find('amendment-form') is not None and root.find('amendment-body') is not None):
            model = xml_element(root)
            fields = {'body_format': ['xml'], 'record_role': ['document'],
                      'content_xml_root': [model.tag], 'content_document_kind': ['amendment']}
            for attribute in ('type', 'stage', 'degree'):
                if value := model.get('amend-' + attribute):
                    fields['content_amendment_' + attribute] = [value]
            if value := model.findtext('amendment-form/legis-num'):
                fields['content_legis_num'] = [value]
            return fields
        parser = {'committee-meeting': parse_house_meeting,
                  'witness-list': parse_house_witnesses}.get(root.tag)
        if parser is None:
            return {}
        model = parser(root)
    except (ValueError, ParseError):
        return {}
    fields = {'source_record_type': [model.tag], 'body_format': ['xml'],
              'record_role': ['source-record' if model.tag == 'committee-meeting' else 'document']}
    if identifier := model.get('meeting-id'):
        fields['source_record_identifier'] = [identifier]
    if model.tag == 'witness-list':
        fields['content_document_kind'] = ['witness-list']
    links = sorted({n.get('doc-url') for n in model.iter('file') if n.get('doc-url')})
    if links:
        fields['source_record_document_url'] = links
    return fields


def document_body_fields(data):
    """Identify ambiguous bytes independently of names, headers, and HTTP status."""
    if data is None:
        return {}
    if data.lstrip().startswith(b'%PDF-'):
        return {'body_format': ['pdf']}
    if data.startswith(b'PK\x03\x04') and is_zipfile(BytesIO(data)):
        return {'body_format': ['zip']}
    if data.startswith(b'rtfd'):
        return {'body_format': ['file_wrapper']}
    if fields := house_record(data):
        return fields
    if re.match(br'\s*(?:<!doctype\s+html|<html)\b', data, re.I):
        fields = {'body_format': ['html']}
        title = _PageTitle()
        title.feed(data.decode('utf-8', errors='replace'))
        if ' '.join(''.join(title.parts).split()).casefold() in {
            'not found | committee repository | u.s. house of representatives',
            'page not found | govinfo', 'u.s. senate: 404 error page', '403 forbidden',
        }:
            fields.update(record_role=['error-response'], source_record_type=['error-page'])
        return fields
    return {}


def committee_page(row):
    """Only known committee page routes qualify; generic HTML stays a document."""
    try:
        url = urlsplit(row.get('source_url') or '')
    except ValueError:
        return False
    host = (url.hostname or '').lower()
    return (host.endswith(('.house.gov', '.senate.gov')) or host in {'www.csce.gov', 'csce.gov'}) and bool(
        re.match(r'/(?:activities/)?hearings(?:/|$)|/press-releases/|/media/media-advisories/', url.path))


def cache_marker(row):
    return bool(re.fullmatch(r'\d+\.none', row.get('filename') or '') and any(
        'docs_house_xml' in path.split('/') for path in row.get('source_paths') or []
    ))


def marker_fields(data):
    fields = {'record_role': ['capture-state'], 'source_record_type': ['house-cache-marker'],
              'cache_marker_state': ['unread' if data is None else 'empty' if not data else 'unrecognized']}
    if data:
        try:
            text = data.decode('utf-8').strip()
            url = urlsplit(text)
            if (url.scheme in {'http', 'https'} and url.hostname == 'docs.house.gov'
                    and not re.search(r'\s', text)):
                fields['attempted_url'] = [text]
                fields['cache_marker_state'] = ['url-pointer' if url.path.endswith('.xml') else 'incomplete-url-pointer']
        except (ValueError, UnicodeDecodeError):
            pass
    return fields


def enrich_sources(rows, *, read_body, extract, cached=None, urls=None, initialize_roles=True, shared_body_fields=None):
    """Read native content/format facts; PDF covers are a separate fallback stage.

    Original filenames, URLs, types and statuses stay intact.
    """
    urls = urls if urls is not None else defaultdict(set)
    cached = cached if cached is not None else {}

    def remember(url):
        try:
            parts = urlsplit(url)
            if (parts.scheme in {'http', 'https'}
                    and parts.hostname in {'congress.gov', 'www.congress.gov'}
                    and re.fullmatch(r'/\d+/meeting/house/\d+/documents/[^/]+', parts.path)
                    and not parts.query and not parts.fragment):
                key = legacy_house_cache_name(url)
                candidates = urls[key]
                candidates.add(url)
                urls[key] = candidates
        except ValueError:
            pass

    def read(row):
        key = row.get('body_key')
        # The parsed-field cache handles aliases. Keeping every decompressed body
        # as well makes memory grow with the archive's total uncompressed size.
        return read_body(key) if key else None

    for row in rows:
        if row.get('source_url'):
            remember(row['source_url'])
        if initialize_roles:
            row['record_role'] = ['error-response' if row.get('source_record_type') == ['error-page']
                              else 'source-record' if row.get('source_record_type') else 'document']
        paths = row.get('source_paths') or []
        if (not row.get('source_url') and row.get('filename_origins') == ['retained_path']
                and paths and all(re.fullmatch(
                    r'raw-source-backfill-\d{8}/documents/metadata-review/[^/]+\.py\.before', path)
                    and path.rsplit('/', 1)[-1] == row.get('filename') for path in paths)):
            # Collector backups imported with the archive are capture evidence.
            # The basename alone cannot establish this role for a public link.
            row['record_role'] = ['capture-state']
            row['source_record_type'] = ['collector-artifact']
        elif cache_marker(row):
            key = ('marker', row.get('body_key'))
            if key not in cached:
                data = read(row)
                if data is not None:
                    cached[key] = marker_fields(data)
            row.update(cached.get(key, marker_fields(None)))
        elif (re.fullmatch(r'\d+\.xml', row.get('filename') or '')
              or ((row.get('filename') or '').lower().endswith('.xml') and not row.get('document_kind'))):
            key = ('xml', row.get('body_key'))
            if key not in cached:
                data = read(row)
                if data is not None:
                    cached[key] = house_record(data)
            fields = cached.get(key, {})
            row.update(fields)
            for url in fields.get('source_record_document_url', ()):
                remember(url)

    # Share only evidence admitted by the original per-call body pass. A typed
    # XML alias alone does not opt into native evidence; an anonymous alias can
    # establish it for identical bytes in a later batch.
    body_fields = shared_body_fields if shared_body_fields is not None else {}
    for row in rows:
        if ('document', row.get('body_key')) in cached:
            body_fields.setdefault(row['body_key'], cached[('document', row['body_key'])])
    for row in rows:
        name = row.get('filename') or ''
        encoded = ENCODED_NAME.match(name)
        # Normal named PDFs already have a bounded cover reader. Inspect missing
        # or misleading format hints, including anonymous copies and HTML caches.
        if row.get('record_role') in (['source-record'], ['capture-state']):
            continue
        if not row.get('body_key') or (not encoded and (row.get('document_kind')
                or name.lower().endswith(('.pdf', '.xml')))):
            continue
        candidates = sorted(urls.get(row['filename'], ()))
        names = {unquote(urlsplit(url).path.rsplit('/', 1)[-1]) for url in candidates}
        if len(names) == 1:
            name, = names
            # Interpret the publisher name instead of accumulating spurious
            # subjects/dates from a local cache key. The literal key stays saved.
            for field in extract((row['filename'], row.get('source_url'))):
                row.pop(field, None)
            row.update(extract((name, candidates[0])))
            row['recovered_filename'] = [name]
            row['recovered_source_url'] = candidates
        key = ('xml' if cached.get(('xml', row.get('body_key'))) else 'document', row.get('body_key'))
        if key in cached:
            row.update(cached[key])
            body_fields[row.get('body_key')] = cached[key]
            continue
        data = read(row)
        if data is None:
            continue
        body_fields[row['body_key']] = document_body_fields(data)
        row.update(body_fields[row['body_key']])
        cached[key] = body_fields[row['body_key']]
    for row in rows:
        # The same retained bytes cannot be PDF at one URL and a Not Found page
        # at another. Keep native response headers intact alongside body evidence.
        row.update(body_fields.get(row.get('body_key'), {}))
        if (row.get('body_format') == ['html'] and not row.get('document_kind')
                and not row.get('source_record_type') and committee_page(row) and not response_failed(row)):
            row['record_role'] = ['source-record']
            row['source_record_type'] = ['committee-page']
        # Apply capture-specific failures after body evidence has been shared.
        # A failed retrieval must never poison the cache for identical bytes
        # successfully captured elsewhere, nor replace source/marker roles.
        apply_response_role(row)
    return rows


def enrich_document_covers(rows, *, read_body, cached=None):
    """Fill untyped retained PDFs from explicit covers, once per body.

    Known filename/source types need no PDF extraction. Content facts follow
    identical bytes across aliases; capture failures stay capture-specific.
    """
    cached = cached if cached is not None else {}
    covers = {row['body_key']: cached[('cover', row['body_key'])]
              for row in rows if ('cover', row.get('body_key')) in cached}
    covers.update({row['body_key']: {key: row[key] for key in COVER_FIELDS if row.get(key)}
              for row in rows if row.get('body_key') and row.get('content_document_kind')
              and row.get('body_format') == ['pdf']})
    for row in rows:
        key = row.get('body_key')
        if (not key or key in covers or row.get('document_kind') or row.get('content_document_kind')
                or row.get('record_role') in (['source-record'], ['capture-state'], ['error-response'])
                or response_failed(row)):
            continue
        if (row.get('body_format') != ['pdf'] and row.get('format') != ['pdf']
                and not (row.get('filename') or '').lower().endswith('.pdf')
                and not any(value.split(';')[0].strip().lower() == 'application/pdf' for value in row.get('media_type') or [])):
            continue
        data = read_body(key)
        if data is not None:
            covers[key] = document_cover(data)
            cached[('cover', key)] = covers[key]
    for row in rows:
        if fields := covers.get(row.get('body_key')):
            row.update(fields)
            row['body_format'] = ['pdf']
