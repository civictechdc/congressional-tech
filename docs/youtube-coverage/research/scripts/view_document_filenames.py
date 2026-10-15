"""Review a published filename catalog and its retained documents locally.

Run from the repository root:
    .venv/bin/python docs/youtube-coverage/research/scripts/view_document_filenames.py
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from functools import lru_cache
import gzip
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
import tomllib
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FILE = ROOT / '.cache/congressional-tech-raw/indexes/document-filenames.parquet'
HTML = Path(__file__).resolve().parents[1] / 'filename-viewer.html'
SCRIPT = HTML.with_suffix('.mjs')
LIST_COLUMNS = ('filename', 'source_url', 'body_key', 'congress', 'document_kind', 'document_family',
                'extension', 'committee_code', 'measure_references', 'media_type', 'http_status',
                'source_id', 'document_id', 'format', 'record_role', 'body_format',
                'response_usable', 'response_body_complete', 'response_format', 'response_result',
                'recovered_filename', 'recovered_source_url', 'source_congress')
FILTERS = ('congress', 'document_family', 'document_kind', 'format')


class SnapshotChanged(ValueError):
    pass


def web_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password else None
    except ValueError:
        return None


def api_reference(value):
    """Identify metadata endpoints positively, without guessing from a filename."""
    if not web_url(value):
        return None
    url = urlsplit(value)
    if url.hostname != 'api.congress.gov' or not url.path.startswith('/v3/'):
        return None
    parts = [part for part in url.path.split('/')[2:] if part]
    if not parts:
        return None
    title = parts[0].replace('-', ' ').capitalize()
    if len(parts) >= 4 and parts[1].isdigit() and parts[2] in ('house', 'senate'):
        title = f'{parts[2].capitalize()} {parts[0].replace("-", " ")} {parts[3]} · Congress {parts[1]}'
        if len(parts) > 4:
            title += ' · ' + ' / '.join(parts[4:])
    else:
        title += ' · ' + ' / '.join(parts[1:]) if len(parts) > 1 else ''
    return dict(title=title, evidence='Congress.gov API endpoint URL')


def source_context(record):
    """Keep each publisher page/link association together; never zip flat lists."""
    file_url = web_url(record.get('source_url'))
    recovered = [url for value in record.get('recovered_source_url') or [] if (url := web_url(value))]
    pages, redirects, seen = [], [], set()
    occurrences = record.get('source_occurrences') or []
    for observation in occurrences or [record]:
        basis = observation.get('source_association_basis') or []
        if 'publisher_redirect' in basis and 'linked_page' not in basis and file_url:
            for original in observation.get('source_associated_url') or []:
                if web_url(original) and original != file_url and (original, file_url) not in redirects:
                    redirects.append((original, file_url))
        candidates = any(value not in ('publisher_redirect', 'retained_html_link', 'linked_page') for value in basis)
        urls = list(dict.fromkeys(value for key in ('source_original_page_url', 'source_page_url')
                                 for value in observation.get(key) or [] if web_url(value)))
        urls = [value for value in urls if value != file_url and value not in recovered]
        if not urls:
            continue
        # A title can label a single observed page. Multiple flat titles/URLs
        # are displayed as a group; their positions do not establish pairings.
        page = dict(urls=urls, titles=observation.get('source_page_title') or [],
                    link_labels=observation.get('source_link_label') or [],
                    link_urls=[value for value in observation.get('source_link_url') or [] if web_url(value)],
                    relationship='Possible source page' if candidates else
                    'Linked through' if 'linked_page' in basis else
                    'Linked from' if observation.get('source_occurrence_scope') == ['anchor'] else 'Recorded source page')
        if observation.get('source_page_type'):
            page['types'] = observation['source_page_type']
        if observation.get('source_page_date'):
            page['dates'] = observation['source_page_date']
        identity = json.dumps(page, sort_keys=True)
        if identity not in seen:
            pages.append(page)
            seen.add(identity)
    return dict(file_url=file_url, recovered_urls=recovered, pages=pages,
                redirects=[dict(original=a, final=b) for a, b in redirects])


def video_reference(value):
    from congress_api.parsers.media import youtube_video_id
    identity = youtube_video_id(value) if web_url(value) else None
    return dict(provider='YouTube', id=identity) if identity else None


@lru_cache(maxsize=128)
def filename_reading(filename, source_url):
    from house_naming import Engine, __version__
    result = Engine().extract(filename, source_url=source_url)
    observations = []
    seen = set()
    for observation in result.get('observations', []):
        for field in observation.get('fields', []):
            identity = (field['name'], field['raw'], field.get('note'))
            if identity not in seen:
                observations.append({key: field.get(key) for key in ('name', 'raw', 'note', 'candidates', 'label')})
                seen.add(identity)
    diagnostics = []
    congress = result.get('metadata', {}).get('congress', [])
    if len(congress) > 1:
        readings = []
        for observation in result.get('observations', []):
            for field in observation.get('fields', []):
                if field['name'] == 'congress':
                    readings.append(f'{observation["rule"]} reads {field["raw"]}')
        for match in result.get('matches', []):
            if value := match.get('record', {}).get('congress'):
                readings.append(f'{match["kind"]} convention reads {value}')
        diagnostics.append('Competing Congress extraction: ' + '; '.join(dict.fromkeys(readings)) +
                           '. The viewer preserves both; source context does not resolve the filename.')
    return dict(version=__version__, recognized_convention=result.get('valid', False),
                metadata=result.get('metadata', {}), observations=observations, diagnostics=diagnostics)


class RetainedFiles:
    """Read exact retained objects locally or through configured Cloudflare access."""
    def __init__(self, roots, cache, account_id=None, profile=None):
        self.roots = [Path(root).resolve() for root in roots]
        self.cache, self.account_id, self.profile = Path(cache), account_id, profile

    def compressed(self, key):
        if (not isinstance(key, str) or '..' in key.split('/') or
                not re.fullmatch(r'(?:bodies/sha256/[a-f0-9]{2}/[a-f0-9]{64}|receipts/[A-Za-z0-9_./-]+\.jsonl)\.gz', key)):
            raise ValueError('Invalid retained-object location.')
        for root in [self.cache.resolve(), *self.roots]:
            path = (root / key).resolve()
            if not path.is_relative_to(root):
                raise ValueError('Retained-object location leaves the archive.')
            if path.is_file():
                if path.stat().st_size > 64 * 1024**2:
                    raise ValueError('Saved file exceeds the viewer’s 64 MiB limit.')
                return path.read_bytes()
        if not self.account_id:
            raise FileNotFoundError('Saved file is not available locally. Configure R2 access to read it.')
        profile = Path(self.profile) if self.profile else Path.home() / 'Library/Preferences/.wrangler/config/default.toml'
        token = os.environ.get('CLOUDFLARE_API_TOKEN')
        if not token and profile.is_file():
            token = tomllib.loads(profile.read_text()).get('oauth_token')
        if not token:
            raise FileNotFoundError('Cloudflare access is not configured. Sign in with Wrangler, then retry.')
        if not re.fullmatch(r'[a-f0-9]{32}', self.account_id):
            raise ValueError('Invalid Cloudflare account ID.')
        url = f'https://api.cloudflare.com/client/v4/accounts/{self.account_id}/r2/buckets/congressional-tech-raw/objects/{quote(key, safe="/")}'
        try:
            with urlopen(Request(url, headers={'Authorization': 'Bearer ' + token}), timeout=40) as response:
                data = response.read(64 * 1024**2 + 1)
        except HTTPError as error:
            if error.code in (401, 403):
                raise FileNotFoundError('Cloudflare access expired or was denied. Refresh the Wrangler login, then retry.') from error
            raise FileNotFoundError(f'Unable to read the saved object from R2 (HTTP {error.code}).') from error
        if len(data) > 64 * 1024**2:
            raise ValueError('Saved file exceeds the viewer’s 64 MiB limit.')
        destination = self.cache / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        # A unique staging directory keeps concurrent requests from sharing a partial file.
        with TemporaryDirectory(dir=destination.parent) as temporary:
            stage = Path(temporary) / 'object.gz'
            stage.write_bytes(data)
            stage.replace(destination)
        return data

    def body(self, record):
        from congress_api.retention.document_evidence import read_retained_body
        # Read first so access failures retain their useful error messages.
        compressed = self.compressed(record.get('body_key'))
        data = read_retained_body(None, record.get('body_key'), read_compressed=lambda _: compressed, limit=64 * 1024**2)
        if data is None:
            raise ValueError('The saved file has an invalid body location or exceeds the 64 MiB inspection limit.')
        return data

    def receipt(self, record):
        """Verify receipt/body association before returning a small safe summary."""
        observations = record.get('source_occurrences') or [record]
        checked = set()
        for observation in observations:
            for key in observation.get('source_receipt_key') or []:
                for line in observation.get('source_receipt_line') or []:
                    if (key, line) in checked:
                        continue
                    checked.add((key, line))
                    if len(checked) > 64:
                        return None
                    if not str(line).isdigit() or int(line) < 1:
                        continue
                    from io import BytesIO
                    with gzip.GzipFile(fileobj=BytesIO(self.compressed(key))) as stream:
                        decoded = stream.read(32 * 1024**2 + 1)
                    if len(decoded) > 32 * 1024**2:
                        raise ValueError('Receipt exceeds the viewer’s inspection limit.')
                    lines = decoded.splitlines()
                    if int(line) > len(lines):
                        continue
                    item = json.loads(lines[int(line) - 1])
                    captures = item.get('captures') or []
                    if not any(capture.get('body_key') == record.get('body_key') for capture in captures):
                        continue
                    source = item.get('record') or {}
                    return {key: source.get(key) for key in ('retrieved_at', 'requested_url', 'url', 'http_status', 'complete')}
        return None

    def inspect(self, record):
        data = self.body(record)
        result = dict(bytes=len(data), sha256=sha256(data).hexdigest(), verified=True, pages=[], content_fields={})
        try:
            result['receipt'] = self.receipt(record)
        except (OSError, ValueError, EOFError):
            result['receipt_error'] = 'Saved-file integrity passed, but capture details could not be read.'
        if not data.lstrip().startswith(b'%PDF-'):
            result['note'] = 'Saved bytes verified. Text inspection is available for PDFs only.'
            return result
        if len(data) > 16 * 1024**2:
            result['note'] = 'Saved bytes verified. This PDF exceeds the 16 MiB text-inspection limit.'
            return result
        from congress_api.parsers.pdf_tools import page_count_file, opening_page_text_file
        from congress_api.parsers.document_cover import document_page_fields
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / 'document.pdf'
            path.write_bytes(data)
            try:
                result['page_count'] = page_count_file(path)
                for number in range(1, min(2, result['page_count']) + 1):
                    result['pages'].append(dict(number=number, text=opening_page_text_file(path, number)))
                texts = [page['text'] for page in result['pages']]
                result['content_fields'] = document_page_fields(texts[0], texts[1] if len(texts) > 1 else '')
                result['note'] = 'Read now from the first two saved PDF pages. These observations do not change the published catalog. Scanned pages may have no extractable text.'
            except (OSError, ValueError) as error:
                result['note'] = 'Saved bytes verified. PDF text inspection was unavailable: ' + str(error)
        return result


class Catalog:
    def __init__(self, path: Path, retained=None):
        from congress_api.retention.catalog_publication import local_catalog_paths
        if path.name == 'document-filenames.parquet' and path.parent.name == 'indexes':
            path, documents = local_catalog_paths(path.parent.parent)
        else:
            documents = path.with_name('documents.parquet')
        self.path = path
        self.retained = retained
        self.file = pq.ParquetFile(path)
        self.document_path = documents
        if not self.document_path.is_file():
            raise ValueError('Build the root document index first with index_document_filenames.py --documents-only.')
        self.document_file = pq.ParquetFile(self.document_path)
        catalog_id = (self.file.schema_arrow.metadata or {}).get(b'catalog_id')
        if not catalog_id or catalog_id != (self.document_file.schema_arrow.metadata or {}).get(b'catalog_id'):
            raise ValueError('The document indexes are from different builds. Rebuild them together.')
        self.fields = self.file.schema_arrow.names
        self.table = self.file.read(columns=[c for c in LIST_COLUMNS if c in self.fields])
        self.documents = self.document_file.read(columns=[c for c in LIST_COLUMNS if c in self.fields])
        entries = {key: i for i, key in enumerate(self.documents['document_id'].to_pylist())}
        sources = {key: i for i, key in enumerate(self.table['source_id'].to_pylist())}
        self.source_ids = sources
        self.entry_ids = [entries[key] for key in self.table['document_id'].to_pylist()]
        self.members = [[] for _ in range(len(self.documents))]
        for row_id, entry in enumerate(self.entry_ids):
            self.members[entry].append(row_id)
        self.saved_responses = bytearray(len(self.documents))
        for row_id in pc.indices_nonzero(pc.is_valid(self.table['body_key'])).to_pylist():
            self.saved_responses[self.entry_ids[row_id]] = 1
        self.preferred_sources = [sources[key] for key in self.documents['source_id'].to_pylist()]
        self.order = pc.sort_indices(self.documents, sort_keys=[('filename', 'ascending')])
        self.document_entries = set(
            i for i, roles in enumerate(self.documents['record_role'].to_pylist())
            if roles == ['document']
        ) if 'record_role' in self.documents.column_names else set(range(len(self.documents)))
        urls = self.table['source_url']
        api_mask = pc.or_(pc.starts_with(urls, 'https://api.congress.gov/v3/'),
                          pc.starts_with(urls, 'http://api.congress.gov/v3/'))
        self.api_sources = {
            row_id: reference for row_id in pc.indices_nonzero(pc.fill_null(api_mask, False)).to_pylist()
            if (reference := api_reference(urls[row_id].as_py()))
        }
        # Preserve mixed groups containing an actual document URL. Only groups
        # whose every member is a known metadata endpoint leave Documents.
        self.api_entries = {self.entry_ids[row_id] for row_id in self.api_sources}
        self.api_entries = {entry for entry in self.api_entries
                            if all(row_id in self.api_sources for row_id in self.members[entry])}
        self.document_entries.difference_update(self.api_entries)
        video_mask = pc.match_substring_regex(urls, r'(?i)^https?://(www\.)?(youtu\.be|youtube\.com|youtube-nocookie\.com)/')
        self.video_sources = {
            row_id: reference for row_id in pc.indices_nonzero(pc.fill_null(video_mask, False)).to_pylist()
            if (reference := video_reference(urls[row_id].as_py()))
        }
        self.video_entries = {self.entry_ids[row_id] for row_id in self.video_sources}
        self.video_entries = {entry for entry in self.video_entries
                              if all(row_id in self.video_sources for row_id in self.members[entry])}
        self.document_entries.difference_update(self.video_entries)
        self.group_starts = [0]
        for group in range(self.file.num_row_groups):
            self.group_starts.append(self.group_starts[-1] + self.file.metadata.row_group(group).num_rows)
        self.document_starts = [0]
        for group in range(self.document_file.num_row_groups):
            self.document_starts.append(self.document_starts[-1] + self.document_file.metadata.row_group(group).num_rows)
        self.filter_text = {}
        facets = {}
        for field in FILTERS:
            column = (self.table[field] if field in self.table.column_names else
                      pa.nulls(len(self.table), type=pa.list_(pa.string())))
            values = pc.list_flatten(column)
            joined = pc.binary_join(column, '\0')
            if field == 'format':
                values, joined = pc.utf8_lower(values), pc.utf8_lower(joined)
            facets[field] = sorted(v for v in pc.unique(values).to_pylist() if v)
            self.filter_text[field] = pc.binary_join_element_wise('\0', joined, '\0', '')
        self.info = {
            'file': path.name, 'rows': len(self.table),
            'filenames': pc.count_distinct(self.table['filename']).as_py(),
            'entries': len(self.members),
            'documents': len(self.document_entries),
            'capture_records': len(self.members) - len(self.document_entries),
            'api_reference_groups': len(self.api_entries),
            'video_reference_groups': len(self.video_entries),
            'bytes': path.stat().st_size, 'fields': self.fields, 'facets': facets,
            'catalog_id': catalog_id.decode(),
            'house_naming_version': (self.file.schema_arrow.metadata or {}).get(b'house_naming_version', b'unknown').decode(),
        }
        archive = path.parents[2] if path.parent.parent.name == 'catalog-generations' else path.parent.parent
        receipt = archive / 'sync-receipt.json'
        if receipt.is_file():
            sync = json.loads(receipt.read_text())
            if sync.get('catalog_id') == self.info['catalog_id']:
                self.info.update({key: sync.get(key) for key in ('generation', 'synced_at', 'remote_last_modified')})

    def resolve(self, identity, catalog_id=None):
        if catalog_id and catalog_id != self.info['catalog_id']:
            raise SnapshotChanged('This link belongs to a different catalog snapshot. Close this panel and select the document in the current results.')
        if identity in self.source_ids:
            return self.source_ids[identity]
        if identity.isdecimal() and len(identity) < 12:
            row = int(identity)
            if row < len(self.table):
                return row
        raise ValueError('Source record is not present in this catalog.')

    @lru_cache(maxsize=4)
    def searchable(self, field):
        if field not in self.fields:
            raise ValueError('Unknown search column.')
        column = self.table[field] if field in LIST_COLUMNS else self.file.read(columns=[field])[field]
        if pa.types.is_list(column.type) and pa.types.is_struct(column.type.value_type):
            return pa.array([json.dumps(value, ensure_ascii=False) if value else None
                             for value in column.to_pylist()], type=pa.string())
        return pc.binary_join(column, ' | ') if pa.types.is_list(column.type) else column

    def search(self, query):
        text = query.get('q', '')[:2000]
        field = query.get('field', 'filename')
        if field == 'publication_code_code' and field not in self.fields:
            field = 'publication_type'  # Preserve bookmarked filters after consolidation.
        if field not in self.fields:
            raise ValueError('Unknown search column.')
        mask = pa.array([True] * len(self.table))
        if text:
            found = pc.fill_null(pc.match_substring(self.searchable(field), text, ignore_case=True), False)
            if field == 'filename' and 'recovered_filename' in self.fields:
                found = pc.or_(found, pc.fill_null(pc.match_substring(
                    self.searchable('recovered_filename'), text, ignore_case=True), False))
            mask = pc.and_(mask, found)
        for name in FILTERS:
            value = query.get(name, query.get('extension', '') if name == 'format' else '')
            if name in ('document_kind', 'document_family') and value == '__null__':
                continue  # Check the grouped document, not an unclassified alias.
            if value:
                if value not in self.info['facets'][name]:
                    raise ValueError(f'Unknown {name} filter.')
                mask = pc.and_(mask, pc.fill_null(pc.match_substring(self.filter_text[name], '\0' + value + '\0'), False))
        retained = query.get('retained', '')
        if retained not in ('', 'yes', 'no'):
            raise ValueError('Unknown retained-file filter.')
        matching_entries = {self.entry_ids[row_id] for row_id in pc.indices_nonzero(mask).to_pylist()}
        if retained:
            # A missing alias does not make the whole document unsaved. Check
            # all group members, including URLs excluded by the other filters.
            matching_entries = {entry for entry in matching_entries
                                if bool(self.saved_responses[entry]) == (retained == 'yes')}
        scope = query.get('scope', '')
        if scope not in ('', 'all', 'capture-records'):
            raise ValueError('Unknown record scope.')
        if not scope:
            matching_entries.intersection_update(self.document_entries)
        elif scope == 'capture-records':
            matching_entries.difference_update(self.document_entries)
        for name in ('document_kind', 'document_family'):
            if query.get(name) == '__null__':
                column = (self.documents[name] if name in self.documents.column_names else
                          pa.nulls(len(self.documents), type=pa.list_(pa.string())))
                missing = pc.equal(pc.fill_null(pc.list_value_length(column), 0), 0)
                matching_entries.intersection_update(pc.indices_nonzero(missing).to_pylist())
        matches = [entry for entry in self.order.to_pylist() if entry in matching_entries]
        total = len(matches)
        limit = max(1, min(100, int(query.get('limit', 50))))
        pages = max(1, (total + limit - 1) // limit)
        page = max(1, min(pages, int(query.get('page', 1))))
        selected = matches[(page - 1) * limit:page * limit]
        rows = self.documents.take(pa.array(selected, type=pa.int64())).to_pylist()
        for row, entry in zip(rows, selected):
            row['_row'] = self.preferred_sources[entry]
            row['source_count'] = len(self.members[entry])
            row.pop('body_key')
            row['retained'] = bool(self.saved_responses[entry])
            row['api_reference'] = self.api_sources.get(self.preferred_sources[entry]) if entry in self.api_entries else None
            row['video_reference'] = self.video_sources.get(self.preferred_sources[entry]) if entry in self.video_entries else None
        return {'rows': rows, 'total': total, 'page': page, 'pages': pages, 'limit': limit}

    @lru_cache(maxsize=16)
    def record(self, row_id):
        if row_id < 0 or row_id >= len(self.table):
            raise ValueError('Row does not exist.')
        group = bisect_right(self.group_starts, row_id) - 1
        # Read all columns only for the selected row's group, never for the whole catalog.
        return self.file.read_row_group(group).slice(row_id - self.group_starts[group], 1).to_pylist()[0]

    def entry(self, row_id):
        record = self.record(row_id)
        ids = self.members[self.entry_ids[row_id]]
        sources = self.table.take(pa.array(ids, type=pa.int64())).to_pylist()
        bodies = [source.get('body_key') for source in sources]
        for source, source_id in zip(sources, ids):
            source['_row'] = source_id
            source['retained'] = source.pop('body_key') is not None
        filename = self.documents['filename'][self.entry_ids[row_id]].as_py()
        position = self.entry_ids[row_id]
        group = bisect_right(self.document_starts, position) - 1
        document = self.document_file.read_row_group(group).slice(position - self.document_starts[group], 1).to_pylist()[0]
        reading = filename_reading(record['filename'], record.get('source_url')) if record.get('filename') else None
        return {'record': record, 'document': document, 'filename': filename, 'sources': sources,
                'api_reference': self.api_sources.get(row_id),
                'video_reference': self.video_sources.get(row_id),
                'catalog_id': self.info['catalog_id'], 'reading': reading,
                'origin': source_context(record),
                'document_origin': source_context(self.record(self.preferred_sources[position])),
                'sources_share_saved_file': bool(bodies and bodies[0] and len(set(bodies)) == 1),
                'saved_file_available': bool(self.retained and record.get('body_key'))}

    @lru_cache(maxsize=16)
    def evidence(self, row_id):
        if self.retained is None:
            raise FileNotFoundError('Saved-file access is not configured.')
        return self.retained.inspect(self.record(row_id))


def handler_for(catalog):
    class Handler(BaseHTTPRequestHandler):
        def send(self, content, content_type, status=200):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)

        def json(self, payload, status=200):
            self.send(json.dumps(payload, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status)

        def do_GET(self):
            # The local reader may hold Cloudflare credentials. Do not let a
            # different hostname reuse it through DNS rebinding.
            port = self.server.server_address[1]
            if self.headers.get('Host') not in {f'127.0.0.1:{port}', f'localhost:{port}'}:
                self.json({'error': 'Open this viewer through its localhost address.'}, 403)
                return
            url = urlsplit(self.path)
            try:
                query = {k: v[-1] for k, v in parse_qs(url.query).items()}
                if url.path == '/':
                    self.send(HTML.read_bytes(), 'text/html; charset=utf-8')
                elif url.path == '/filename-viewer.mjs':
                    self.send(SCRIPT.read_bytes(), 'text/javascript; charset=utf-8')
                elif url.path == '/api/info':
                    self.json(catalog.info)
                elif url.path == '/api/rows':
                    self.json(catalog.search({k: v[-1] for k, v in parse_qs(url.query).items()}))
                elif url.path.startswith('/api/row/'):
                    self.json(catalog.record(int(url.path.removeprefix('/api/row/'))))
                elif url.path.startswith('/api/entry/'):
                    row = catalog.resolve(url.path.removeprefix('/api/entry/'), query.get('catalog'))
                    self.json(catalog.entry(row))
                elif url.path.startswith('/api/evidence/'):
                    row = catalog.resolve(url.path.removeprefix('/api/evidence/'), query.get('catalog'))
                    self.json(catalog.evidence(row))
                elif url.path.startswith('/saved/'):
                    row = catalog.resolve(url.path.removeprefix('/saved/'), query.get('catalog'))
                    if catalog.retained is None:
                        raise FileNotFoundError('Saved-file access is not configured.')
                    record = catalog.record(row)
                    data = catalog.retained.body(record)
                    pdf = data.lstrip().startswith(b'%PDF-')
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/pdf' if pdf else 'application/octet-stream')
                    self.send_header('Content-Length', str(len(data)))
                    name = quote(Path(record.get('filename') or 'saved-document').name, safe='')
                    self.send_header('Content-Disposition', ('inline' if pdf else 'attachment') + "; filename*=UTF-8''" + name)
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    # CSP sandbox can disable native PDF viewers. Other formats
                    # download as octet-stream and cannot become active pages.
                    policy = "default-src 'none'; frame-ancestors 'none'"
                    self.send_header('Content-Security-Policy', policy if pdf else policy + '; sandbox')
                    self.end_headers()
                    self.wfile.write(data)
                elif url.path in ('/data.parquet', '/sources.parquet'):
                    path = catalog.document_path if url.path == '/data.parquet' else catalog.path
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/vnd.apache.parquet')
                    self.send_header('Content-Disposition', f'attachment; filename="{path.name}"')
                    self.send_header('Content-Length', str(path.stat().st_size))
                    self.end_headers()
                    with path.open('rb') as source:
                        shutil.copyfileobj(source, self.wfile)
                elif url.path == '/favicon.ico':
                    self.send(b'', 'image/x-icon', 204)
                else:
                    self.json({'error': 'Not found.'}, 404)
            except SnapshotChanged as exc:
                self.json({'error': str(exc)}, 409)
            except FileNotFoundError as exc:
                self.json({'error': str(exc)}, 404)
            except URLError:
                self.json({'error': 'The archive could not be reached. Retry saved-file access.'}, 502)
            except (ValueError, pa.ArrowInvalid) as exc:
                self.json({'error': str(exc)}, 400)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A new search can cancel an older browser request.
            except (OSError, EOFError):
                self.json({'error': 'The saved object could not be read. Check archive access and retry.'}, 502)

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    synced = ROOT / '.cache/filename-viewer-r2/indexes/document-filenames.parquet'
    default = synced if (synced.parent / 'catalog.json').is_file() else DEFAULT_FILE
    parser.add_argument('file', nargs='?', type=Path, default=default)
    parser.add_argument('--port', type=int, default=8785)
    parser.add_argument('--body-root', action='append', type=Path, default=[ROOT / '.cache/congressional-tech-raw'])
    parser.add_argument('--r2-account-id', default=os.environ.get('CLOUDFLARE_ACCOUNT_ID'))
    parser.add_argument('--cloudflare-profile', type=Path)
    args = parser.parse_args()
    retained = RetainedFiles(args.body_root, ROOT / '.cache/filename-viewer-r2', args.r2_account_id, args.cloudflare_profile)
    catalog = Catalog(args.file.resolve(), retained=retained)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(catalog))
    print(f'Filename viewer: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'{catalog.info["rows"]:,} rows from {catalog.path}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
