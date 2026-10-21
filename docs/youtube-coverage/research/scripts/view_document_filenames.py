"""Review a published filename catalog and its retained documents locally.

Run from the repository root:
    .venv/bin/python docs/youtube-coverage/research/scripts/view_document_filenames.py
"""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urlsplit

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from viewer_publication.filename_viewer import (
    Catalog,
    FILTERS,
    GROUP_COLUMNS,
    LIST_COLUMNS,
    RetainedFiles,
    SnapshotChanged,
    api_reference,
    filename_reading,
    positive_integer,
    source_context,
    video_reference,
    web_url,
)

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FILE = ROOT / '.cache/congressional-tech-raw/indexes/document-filenames.parquet'
HTML = Path(__file__).resolve().parents[1] / 'filename-viewer.html'
SCRIPT = HTML.with_suffix('.mjs')


def handler_for(catalog):
    class Handler(BaseHTTPRequestHandler):
        def send(self, content, content_type, status=200, *, attachment=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            if attachment:
                self.send_header('Content-Disposition', f'attachment; filename="{attachment}"')
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
                    shell = HTML.read_bytes()
                    marker = b'<!-- filename-viewer:body -->'
                    if shell.count(marker) != 1:
                        raise ValueError('Filename viewer shell needs exactly one body marker')
                    self.send(shell.replace(marker, HTML.with_name('filename-viewer-body.html').read_bytes()), 'text/html; charset=utf-8')
                elif url.path == '/filename-viewer.css':
                    self.send(HTML.with_suffix('.css').read_bytes(), 'text/css; charset=utf-8')
                elif url.path in {'/filename-adapter.mjs', '/filename-viewer.mjs', '/filename-rules.mjs', '/filename-provenance.mjs', '/filename-detail-state.mjs'}:
                    self.send(SCRIPT.with_name(url.path[1:]).read_bytes(), 'text/javascript; charset=utf-8')
                elif url.path == '/api/info':
                    self.json(catalog.info)
                elif url.path == '/api/rows':
                    self.json(catalog.search({k: v[-1] for k, v in parse_qs(url.query).items()}))
                elif url.path.startswith('/api/row/'):
                    if catalog.native_snapshot is not None:
                        raise ValueError('Selected native catalogs require stable source IDs.')
                    self.json(catalog.record(int(url.path.removeprefix('/api/row/'))))
                elif url.path.startswith('/api/entry/'):
                    row = catalog.resolve(url.path.removeprefix('/api/entry/'), query.get('catalog'))
                    self.json(catalog.entry(row))
                elif url.path.startswith('/api/evidence/'):
                    row = catalog.resolve(url.path.removeprefix('/api/evidence/'), query.get('catalog'))
                    self.json(catalog.evidence(row))
                elif url.path.startswith('/api/review/'):
                    row = catalog.resolve(url.path.removeprefix('/api/review/'), query.get('catalog'))
                    if query.get('selection', 'review') not in {'review', 'baseline'}:
                        raise ValueError('Unknown review selection.')
                    self.json(catalog.review(row, withdrawn=query.get('selection') == 'baseline'))
                elif url.path.startswith('/review-evidence/'):
                    row = catalog.resolve(url.path.removeprefix('/review-evidence/'), query.get('catalog'))
                    page = int(query['page']) if 'page' in query else None
                    data, content_type = catalog.review_evidence(row, query.get('kind'), page)
                    self.send(data, content_type, attachment='reviewed-document.pdf' if content_type == 'application/pdf' else None)
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
                elif url.path == '/api/selection' and catalog.native_snapshot is not None:
                    self.json(dict(manifest=catalog.native_snapshot.manifest, identity=catalog.native_snapshot.identity))
                elif url.path.startswith('/api/document/'):
                    row = catalog.resolve(url.path.removeprefix('/api/document/'), query.get('catalog'))
                    self.json(catalog.document(row))
                elif url.path in ('/data.parquet', '/sources.parquet'):
                    if catalog.native_snapshot is not None:
                        raise FileNotFoundError('Selected native catalogs expose logical tables, not full Parquet exports.')
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
    parser.add_argument('--catalog-root', type=Path, help='Local store containing an adopted native indexes/catalog.json')
    parser.add_argument('--native-config', type=Path, help='Explicit DocSpec runtime for --catalog-root')
    parser.add_argument('--port', type=int, default=8785)
    parser.add_argument('--body-root', action='append', type=Path, default=[ROOT / '.cache/congressional-tech-raw'])
    parser.add_argument('--r2-account-id', default=os.environ.get('CLOUDFLARE_ACCOUNT_ID'))
    parser.add_argument('--cloudflare-profile', type=Path)
    parser.add_argument('--review-manifest', type=Path, help='Optional portable complete-body review manifest')
    parser.add_argument('--review-sha256', help='Expected SHA-256 of that manifest')
    args = parser.parse_args()
    retained = RetainedFiles(args.body_root, ROOT / '.cache/filename-viewer-r2', args.r2_account_id, args.cloudflare_profile)
    if bool(args.catalog_root) != bool(args.native_config):
        parser.error('--catalog-root and --native-config are required together')
    source = args.file.resolve()
    if args.catalog_root:
        from congress_api.retention.docspec import NativeDatasets
        from congress_api.retention.catalog_cache import LocalStore
        from congress_api.retention.catalog_publication import read_catalog
        source = read_catalog(LocalStore(args.catalog_root), native=NativeDatasets.from_config(args.native_config))
    catalog = Catalog(source, retained=retained,
                      review_manifest=args.review_manifest, review_sha256=args.review_sha256)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(catalog))
    print(f'Filename viewer: http://127.0.0.1:{server.server_port}', flush=True)
    print(f'{catalog.info["rows"]:,} rows from {catalog.path or catalog.native_snapshot.identity}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        catalog.close()


if __name__ == '__main__':
    main()
