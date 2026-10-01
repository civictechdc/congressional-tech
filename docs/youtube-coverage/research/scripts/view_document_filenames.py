"""Browse the filename Parquet locally: no build, copied dataset, or new dependencies.

Run from the repository root:
    .venv/bin/python docs/youtube-coverage/research/scripts/view_document_filenames.py
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
from urllib.parse import parse_qs, urlsplit

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FILE = ROOT / '.cache/congressional-tech-raw/indexes/document-filenames.parquet'
HTML = Path(__file__).resolve().parents[1] / 'filename-viewer.html'
LIST_COLUMNS = ('filename', 'source_url', 'body_key', 'congress', 'document_kind',
                'extension', 'committee_code', 'measure_references', 'media_type', 'http_status',
                'source_id', 'document_id', 'format')
FILTERS = ('congress', 'document_kind', 'format')


class Catalog:
    def __init__(self, path: Path):
        self.path = path
        self.file = pq.ParquetFile(path)
        self.document_path = path.with_name('documents.parquet')
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
        self.entry_ids = [entries[key] for key in self.table['document_id'].to_pylist()]
        self.members = [[] for _ in range(len(self.documents))]
        for row_id, entry in enumerate(self.entry_ids):
            self.members[entry].append(row_id)
        self.preferred_sources = [sources[key] for key in self.documents['source_id'].to_pylist()]
        self.order = pc.sort_indices(self.documents, sort_keys=[('filename', 'ascending')])
        self.group_starts = [0]
        for group in range(self.file.num_row_groups):
            self.group_starts.append(self.group_starts[-1] + self.file.metadata.row_group(group).num_rows)
        self.filter_text = {}
        facets = {}
        for field in FILTERS:
            values = pc.list_flatten(self.table[field])
            joined = pc.binary_join(self.table[field], '\0')
            if field == 'format':
                values, joined = pc.utf8_lower(values), pc.utf8_lower(joined)
            facets[field] = sorted(v for v in pc.unique(values).to_pylist() if v)
            self.filter_text[field] = pc.binary_join_element_wise('\0', joined, '\0', '')
        self.info = {
            'file': path.name, 'rows': len(self.table),
            'filenames': pc.count_distinct(self.table['filename']).as_py(),
            'entries': len(self.members),
            'bytes': path.stat().st_size, 'fields': self.fields, 'facets': facets,
        }

    @lru_cache(maxsize=4)
    def searchable(self, field):
        if field not in self.fields:
            raise ValueError('Unknown search column.')
        column = self.table[field] if field in LIST_COLUMNS else self.file.read(columns=[field])[field]
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
            mask = pc.and_(mask, pc.fill_null(pc.match_substring(self.searchable(field), text, ignore_case=True), False))
        for name in FILTERS:
            value = query.get(name, query.get('extension', '') if name == 'format' else '')
            if value:
                if value not in self.info['facets'][name]:
                    raise ValueError(f'Unknown {name} filter.')
                mask = pc.and_(mask, pc.fill_null(pc.match_substring(self.filter_text[name], '\0' + value + '\0'), False))
        retained = query.get('retained', '')
        if retained not in ('', 'yes', 'no'):
            raise ValueError('Unknown retained-file filter.')
        if retained:
            present = pc.is_valid(self.table['body_key'])
            mask = pc.and_(mask, present if retained == 'yes' else pc.invert(present))
        matching_entries = {self.entry_ids[row_id] for row_id in pc.indices_nonzero(mask).to_pylist()}
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
            row['retained'] = row.pop('body_key') is not None
        return {'rows': rows, 'total': total, 'page': page, 'pages': pages, 'limit': limit}

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
        for source, source_id in zip(sources, ids):
            source['_row'] = source_id
            source['retained'] = source.pop('body_key') is not None
        filename = self.documents['filename'][self.entry_ids[row_id]].as_py()
        return {'record': record, 'filename': filename, 'sources': sources}


def handler_for(catalog):
    class Handler(BaseHTTPRequestHandler):
        def send(self, content, content_type, status=200):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(content)

        def json(self, payload, status=200):
            self.send(json.dumps(payload, ensure_ascii=False).encode(), 'application/json; charset=utf-8', status)

        def do_GET(self):
            url = urlsplit(self.path)
            try:
                if url.path == '/':
                    self.send(HTML.read_bytes(), 'text/html; charset=utf-8')
                elif url.path == '/api/info':
                    self.json(catalog.info)
                elif url.path == '/api/rows':
                    self.json(catalog.search({k: v[-1] for k, v in parse_qs(url.query).items()}))
                elif url.path.startswith('/api/row/'):
                    self.json(catalog.record(int(url.path.removeprefix('/api/row/'))))
                elif url.path.startswith('/api/entry/'):
                    self.json(catalog.entry(int(url.path.removeprefix('/api/entry/'))))
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
            except (ValueError, pa.ArrowInvalid) as exc:
                self.json({'error': str(exc)}, 400)
            except (BrokenPipeError, ConnectionResetError):
                pass  # A new search can cancel an older browser request.

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', nargs='?', type=Path, default=DEFAULT_FILE)
    parser.add_argument('--port', type=int, default=8785)
    args = parser.parse_args()
    catalog = Catalog(args.file.resolve())
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
