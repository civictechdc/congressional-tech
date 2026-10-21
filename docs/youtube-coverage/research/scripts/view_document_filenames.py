"""Review a published filename catalog and its retained documents locally.

Run from the repository root:
    .venv/bin/python docs/youtube-coverage/research/scripts/view_document_filenames.py
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

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
    ThreadingHTTPServer,
    api_reference,
    filename_reading,
    handler_for,
    positive_integer,
    source_context,
    video_reference,
    web_url,
)

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_FILE = ROOT / '.cache/congressional-tech-raw/indexes/document-filenames.parquet'


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
    print(f'Filename viewer API: http://127.0.0.1:{server.server_port}', flush=True)
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
