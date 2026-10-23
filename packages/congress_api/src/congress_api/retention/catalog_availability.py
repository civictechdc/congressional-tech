"""Current URL outcomes and hearing-package references, separate from captures.

Relationships do not merge documents, transfer committee context, or claim that
an API metadata response contains the related PDF/HTML bytes.
"""
from collections import defaultdict
import json
import re
from urllib.parse import urlsplit

from congress_api.retention.raw_archive import STATE_KEY

STATE_FIELDS = frozenset({'state_outcome', 'state_body_key', 'state_checked_at',
                          'state_retrieved_at', 'state_family'})
FIELDS = STATE_FIELDS | {'hearing_package_id', 'hearing_resources'}
RESOURCE_FIELDS = ('package_id', 'url', 'body_key', 'format', 'outcome',
                   'association_basis', 'api_response_body_key', 'publisher_format_url')
HEARING = re.compile(r'/v3/hearing/(\d+)/(house|senate|joint)/(\d+)/?')
PACKAGE = re.compile(r'CHRG-\d+(?:hhrg|shrg|jhrg)\d+(?:-[A-Za-z0-9]+)*')


def hearing_package(url):
    """A conventional identifier candidate, not verified publisher identity."""
    try:
        parsed = urlsplit(url or '')
        if (parsed.scheme not in {'http', 'https'} or parsed.hostname != 'api.congress.gov'
                or parsed.username or parsed.password):
            return None
        match = HEARING.fullmatch(parsed.path)
        if match:
            congress, chamber, jacket = match.groups()
            return f'CHRG-{congress}{dict(house="hhrg", senate="shrg", joint="jhrg")[chamber]}{jacket}'
    except ValueError:
        pass
    return None


def package_from_format(url):
    """Read a full package ID only from an official document-content path."""
    try:
        parsed = urlsplit(url or '')
        if (parsed.scheme not in {'http', 'https'} or parsed.hostname not in {
                'www.congress.gov', 'congress.gov', 'www.govinfo.gov', 'govinfo.gov', 'www.gpo.gov', 'gpo.gov'}
                or parsed.username or parsed.password):
            return None
        match = re.fullmatch(r'/(?:content|fdsys)/pkg/([^/]+)/(pdf|html|xml)/([^/]+)', parsed.path)
        if match and PACKAGE.fullmatch(match[1]) and match[3].startswith(match[1] + '.'):
            return match[1]
        if parsed.hostname in {'congress.gov', 'www.congress.gov'}:
            match = re.fullmatch(r'/\d+/chrg/([^/]+)/(?:generated/)?([^/]+)', parsed.path)
            if match and PACKAGE.fullmatch(match[1]) and match[2].startswith(match[1] + '.'):
                return match[1]
    except ValueError:
        pass
    return None


def retained(state):
    return bool(state and state.get('body_key') and state.get('outcome') in {'saved', 'retained', 'html'}
                and state.get('http_status') in (None, 200))


def retained_format(state):
    """A PDF-shaped URL that returned HTML is not a retained PDF."""
    if not retained(state):
        return None
    path = urlsplit(state['url']).path.lower()
    media = (state.get('media_type') or '').split(';', 1)[0].strip().lower()
    if path.endswith('.pdf'):
        if state.get('outcome') != 'html' and media in {'', 'application/pdf', 'application/octet-stream'}:
            return 'pdf'
    elif path.endswith(('.htm', '.html')) and media in {'', 'text/html', 'application/xhtml+xml'}:
        return 'html'
    return None


def _api_formats(record):
    hearing = record.get('hearing')
    if not isinstance(hearing, dict) or not isinstance(hearing.get('formats'), list):
        return None
    # An explicit empty list must not fall back to a guessed package.
    return [(package, item['url']) for item in hearing['formats'] if isinstance(item, dict)
            if (package := package_from_format(item.get('url')))]


def package_dependencies(row):
    """Exact package lookup keys; these relationships never group documents."""
    return {value for value in [hearing_package(row.get('source_url')),
                               package_from_format(row.get('source_url')),
                               *(row.get('hearing_package_id') or [])]
            if isinstance(value, str) and PACKAGE.fullmatch(value)}


def hearing_input_packages(record):
    """Keep endpoint absence dependencies as well as actual publisher packages."""
    if not isinstance(record, dict):
        return set()
    url = record.get('requested_url') or record.get('url') or record.get('_url')
    candidate = hearing_package(url)
    if candidate is None:
        return set()
    formats = _api_formats(record) if record.get('http_status', 200) == 200 else None
    return {candidate, *(package for package, _ in formats or [])}


def annotate_availability(rows, state, *, hearing_records=(), working=None):
    """Cover every current URL and attach qualified hearing resources.

    Existing source rows retain their response facts. New state-only rows cite
    the state index and do not invent receipt locators or successful downloads.
    """
    from congress_api.retention.document_index import url_filename

    by_url = {} if working is None else working.mapping('availability_state')
    resources = defaultdict(list) if working is None else working.mapping('availability_resources')
    # Normal dispatch supplies the raw owner's finite-leaf iterator; legacy
    # full rebuild callers still supply an Arrow table.
    states = (item for batch in state.to_batches(max_chunksize=4096) for item in batch.to_pylist()) if hasattr(state, 'to_batches') else state
    for item in states:
        if 'body_key' not in item and item.get('sha256') is not None:
            from congress_api.retention.raw_storage import format_state_row_for_python
            item = format_state_row_for_python(item)
        if not item.get('url'):
            continue
        if item['url'] in by_url:
            raise ValueError('Duplicate download-state URL in catalog input')
        by_url[item['url']] = item
        package = package_from_format(item['url'])
        kind = retained_format(item)
        if package and kind:
            related = resources.get(package, [])
            related.append(dict(package_id=package, url=item['url'],
                body_key=item['body_key'], format=kind, outcome=item['outcome']))
            resources[package] = related
    seen = {} if working is None else working.mapping('availability_seen')
    package_cache = {} if working is None else working.mapping('availability_package_cache')
    authoritative = {} if working is None else working.mapping('availability_authoritative')
    for record, captures in hearing_records:
        if not isinstance(record, dict) or record.get('http_status', 200) != 200:
            continue
        url = record.get('requested_url') or record.get('url') or record.get('_url')
        formats = _api_formats(record)
        if hearing_package(url) and formats is not None:
            body = next((item['body_key'] for item in captures if item.get('body_key')
                         and json.loads(item.get('pointer_json') or '[]') in [['content', 'body'], ['content'], []]), None)
            # Retain all observed package/format associations across receipts;
            # timestamps cannot prove that a later response invalidates a part.
            path = urlsplit(url).path.rstrip('/')
            declared = authoritative.get(path, [])
            declared.extend((package, exact_url, body) for package, exact_url in formats)
            authoritative[path] = declared

    def annotate(row):
        row = dict(row)
        for name in FIELDS:
            row.pop(name, None)  # Recompute derived state; do not retain stale matches.
        url = row.get('source_url')
        current = by_url.get(url)
        if current:
            for field in STATE_FIELDS:
                value = current.get(field.removeprefix('state_'))
                row[field] = [str(value)] if value is not None else None
        if candidate := hearing_package(url):
            row['source_record_type'] = ['congress-hearing-reference']
            row['record_role'] = ['source-record']
            if url not in package_cache:
                explicit = authoritative.get(urlsplit(url).path.rstrip('/'))
                package_cache[url] = (explicit if explicit is not None else [(candidate, None, None)],
                    'publisher_api_format_package' if explicit is not None else 'endpoint_package_candidate')
            formats, basis = package_cache[url]
            packages = sorted({package for package, _, _ in formats})
            row['hearing_package_id'] = packages or None
            related = [dict(resource, association_basis=basis, api_response_body_key=api_body,
                            publisher_format_url=exact_url)
                       for package, exact_url, api_body in formats for resource in resources.get(package, ())
                       if exact_url is None or (resource['format'] == 'pdf' and urlsplit(exact_url).path.lower().endswith('.pdf'))
                       or (resource['format'] == 'html' and urlsplit(exact_url).path.lower().endswith(('.htm', '.html')))]
            row['hearing_resources'] = sorted(related, key=lambda item: (item['package_id'], item['url'])) or None
        return row

    for row in rows:
        url = row.get('source_url')
        current = by_url.get(url)
        # A link-only row does not expose a saved copy. Keep its original facts
        # and add one state-backed source when the current body is absent.
        matches = bool(current and row.get('body_key') == current.get('body_key'))
        seen[url] = seen.get(url, False) or matches
        yield annotate(row)
    for url, item in by_url.items():
        if url in seen and (seen[url] or not retained(item)):
            continue
        success = retained(item)
        row = dict(body_key=item.get('body_key'), filename=url_filename(url), source_url=url,
                   filename_origins=['download_state'], source_paths=[STATE_KEY],
                   media_type=[item['media_type']] if item.get('media_type') else None,
                   http_status=[str(item['http_status'])] if item.get('http_status') is not None else None)
        if item.get('outcome') != 'retained':
            row['capture_outcome'] = [item['outcome']] if item.get('outcome') else None
        if not success and not item.get('body_key'):
            row.update(record_role=['capture-state'], source_record_type=['download-state'])
        yield annotate(row)
