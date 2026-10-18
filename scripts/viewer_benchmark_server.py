#!/usr/bin/env python3
"""Serve verified local viewer inputs with bounded byte ranges and browser CORS.

No source acquisition or object-store writes occur. Derived benchmark metadata is
kept in --output; the publication and review inputs remain read-only.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/site/scripts'))
from filename_recoveries import index_recoveries, accepted_rows


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def selected_file(root, item):
    path = (root / item['path']).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Invalid publication file path')
    if path.stat().st_size != item['bytes'] or sha(path) != item['sha256']:
        raise ValueError('Publication file differs from manifest: ' + item['path'])
    return path


def cases_for(publication, manifest):
    """Pin detail cases including the largest reconstructed observation record.

    Read bounded dictionary blocks and reference blocks, never either complete
    archival Parquet table. One logical record can exceed the part-size bound.
    """
    import pyarrow as pa
    from array import array
    index = json.loads(selected_file(publication, manifest['files']['observation_index']).read_text())
    def blocks(name, description):
        with selected_file(publication, manifest['files'][name]).open('rb') as stream:
            for block in description['blocks']:
                pieces = []
                for offset, size, decoded in block['parts']:
                    stream.seek(offset)
                    piece = stream.read(size)
                    if len(piece) != size:
                        raise ValueError('Short observation block')
                    pieces.append(pa.decompress(piece, decoded, codec='brotli').to_pybytes())
                values = json.loads(b''.join(pieces))
                if len(values) != block['count']:
                    raise ValueError('Observation block count mismatch')
                yield block['start'], values
    sizes = array('Q')
    for start, values in blocks('observations', index['observations']):
        if start != len(sizes):
            raise ValueError('Noncontiguous observation dictionary')
        sizes.extend(len(encoded(value)) for value in values)
    largest = (0, 0)
    most = (0, 0)
    for start, values in blocks('observation_rows', index['references']):
        for offset, refs in enumerate(values):
            row = start + offset
            count = len(refs or [])
            size = sum(sizes[ref] for ref in refs or [])
            if size > largest[0]:
                largest = (size, row)
            if count > most[0]:
                most = (count, row)
    rows = manifest['info']['rows']
    chosen = sorted({0, rows // 2, rows - 1, largest[1], most[1]}) if rows else []
    ids = {}
    prefix = manifest['ids']
    import struct
    for shard in range(256):
        path = (publication / prefix / f'{shard:02x}.bin').resolve()
        if not path.is_relative_to(publication.resolve()):
            raise ValueError('Invalid source-ID path')
        with path.open('rb') as stream:
            while chunk := stream.read(36 * 4096):
                if len(chunk) % 36:
                    raise ValueError('Invalid source-ID shard length')
                for identity, position in struct.iter_unpack('<32sI', chunk):
                    if position in chosen:
                        ids[position] = identity.hex()
    if set(ids) != set(chosen):
        raise ValueError('Selected browser source IDs are absent')
    cases = [{'id': 'initialize', 'operation': 'initialize'},
             {'id': 'browse', 'operation': 'search', 'query': {}},
             {'id': 'search', 'operation': 'search', 'query': {'q': 'hearing'}}]
    for row in chosen:
        cases.append({'id': f'detail-{row}', 'operation': 'detail', 'source_id': ids[row], 'row': row})
    if chosen:
        cases += [{'id': 'largest-observations', 'operation': 'observations',
                   'source_id': ids[largest[1]], 'row': largest[1], 'limit': 20},
                  {'id': 'largest-origin', 'operation': 'origin', 'source_id': ids[largest[1]], 'row': largest[1]}]
    return {'version': 1, 'catalog_id': manifest['info']['catalog_id'], 'cases': cases,
            'selection': {'largest_observation_json_bytes': largest[0], 'largest_observation_row': largest[1],
                          'most_observations': most[0], 'most_observations_row': most[1],
                          'scope': 'complete published observation dictionary and reference index'}}


def prepare(args):
    publication, output = args.publication.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = publication / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    routes = {}
    release = 'releases/' + sha(manifest_path)[:32] + '/'
    routes['/data/' + release + 'manifest.json'] = manifest_path
    for item in manifest['files'].values():
        routes['/data/' + release + item['path']] = selected_file(publication, item)
    for shard in range(256):
        name = manifest['ids'] + f'{shard:02x}.bin'
        path = (publication / name).resolve()
        if not path.is_relative_to(publication) or not path.is_file() or path.stat().st_size % 36:
            raise ValueError('Invalid source-ID shard')
        routes['/data/' + release + name] = path
    accepted = json.loads(args.accepted.read_text()) if args.accepted else None
    if accepted is not None and (accepted.get('version') != 1 or not isinstance(accepted.get('recoveries'), list)):
        raise ValueError('Invalid accepted recovery input')
    rows = accepted_rows(accepted['recoveries']) if accepted is not None else []
    recovery = encoded(index_recoveries(publication, manifest, rows))
    recovery_hash = hashlib.sha256(recovery).hexdigest()
    recovery_path = f'releases/{recovery_hash[:32]}/{recovery_hash[32:]}/viewer-v2/recovery-status.json'
    routes['/data/' + recovery_path] = recovery
    pointer = {'version': 1, 'catalog_id': manifest['info']['catalog_id'], 'manifest': release + 'manifest.json',
               'recovery': {'path': recovery_path, 'bytes': len(recovery), 'sha256': recovery_hash}}
    routes['/data/manifest.json'] = encoded(pointer)
    descriptor = json.loads(args.review_descriptor.read_text())
    if args.review_data.stat().st_size != descriptor['bytes'] or sha(args.review_data) != descriptor['sha256']:
        raise ValueError('Review data differs from its pinned descriptor')
    routes['/reviews.json'] = args.review_data.resolve()
    cases = json.loads(args.cases.read_text()) if args.cases else cases_for(publication, manifest)
    if cases.get('version') != 1 or cases.get('catalog_id') != manifest['info']['catalog_id']:
        raise ValueError('Browser cases belong to a different catalog')
    if not cases.get('cases') or len({case['id'] for case in cases['cases']}) != len(cases['cases']):
        raise ValueError('Browser cases must have unique IDs')
    review_binding = manifest['files'].get('review_binding')
    binding = json.loads(selected_file(publication, review_binding).read_text()) if review_binding else None
    case_ids = {item['id'] for item in cases['cases']}
    if binding and binding['rows'] and 'bound-review' not in case_ids:
        cases['cases'] += [{'id': 'bound-review', 'operation': 'review', 'row': binding['rows'][0]['sources'][0]}]
    recovery_data = json.loads(recovery)
    if recovery_data['sources'] and 'recovered-link' not in case_ids:
        cases['cases'] += [{'id': 'recovered-link', 'operation': 'recovery', 'row': recovery_data['sources'][0][0]}]
    cases_raw = encoded(cases)
    (output / 'cases.json').write_bytes(cases_raw)
    config = {'version': 1, 'manifest_sha256': sha(manifest_path), 'catalog_id': manifest['info']['catalog_id'],
              'source_manifest': manifest['source_manifest'], 'review_identity_sha256': sha(args.review_identities),
              'review_descriptor': descriptor, 'review_data_sha256': sha(args.review_data),
              'accepted_sha256': sha(args.accepted) if args.accepted else None,
              'recovery_sha256': recovery_hash, 'cases_sha256': hashlib.sha256(cases_raw).hexdigest(),
              'cases': cases, 'expected': {'bound_reviews': len(binding['rows']) if binding else None,
                                         'withdrawn_reviews': len(binding['withdrawn']) if binding else None,
                                         'recovered_sources': len(recovery_data['sources'])}}
    routes['/browser-bundle.js'] = args.bundle.resolve()
    routes['/'] = b'<!doctype html><meta charset="utf-8"><title>Viewer benchmark</title><script src="/browser-bundle.js"></script>'
    return routes, config


def handler(routes):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Headers', 'Range')
            self.send_header('Access-Control-Allow-Methods', 'GET,HEAD,OPTIONS')
            self.end_headers()

        def do_HEAD(self):
            self.serve(head=True)

        def do_GET(self):
            self.serve()

        def serve(self, head=False):
            name = unquote(urlsplit(self.path).path)
            value = routes.get(name)
            if value is None:
                self.send_error(404)
                return
            size = len(value) if isinstance(value, bytes) else value.stat().st_size
            start, end, status = 0, size - 1, 200
            if requested := self.headers.get('Range'):
                match = re.fullmatch(r'bytes=(\d+)-(\d+)', requested)
                if not match or not 0 <= int(match[1]) <= int(match[2]) < size:
                    self.send_error(416)
                    return
                start, end, status = int(match[1]), int(match[2]), 206
            self.send_response(status)
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Content-Type', 'text/html; charset=utf-8' if name == '/' else 'text/javascript' if name.endswith('.js') else
                             mimetypes.guess_type(name)[0] or 'application/octet-stream')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Expose-Headers', 'Content-Range,Content-Length')
            self.send_header('Accept-Ranges', 'bytes')
            if status == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            if head:
                return
            if isinstance(value, bytes):
                self.wfile.write(value[start:end + 1])
            else:
                with value.open('rb') as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        piece = stream.read(min(1024 * 1024, remaining))
                        if not piece:
                            raise OSError('Benchmark served file became shorter')
                        self.wfile.write(piece)
                        remaining -= len(piece)
    return Handler


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('publication', 'output', 'bundle', 'review-data'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--review-descriptor', type=Path, default=ROOT / 'apps/site/document-review-publication.json')
    parser.add_argument('--review-identities', type=Path, default=ROOT / 'apps/site/document-review-identities.json')
    parser.add_argument('--accepted', type=Path)
    parser.add_argument('--cases', type=Path)
    args = parser.parse_args()
    routes, config = prepare(args)
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler(routes))
    port = server.server_port
    config.update(page_url=f'http://localhost:{port}/', data_url=f'http://127.0.0.1:{port}/data/manifest.json',
                  review_url=f'http://127.0.0.1:{port}/reviews.json')
    (args.output / 'server-config.json').write_text(json.dumps(config, indent=2) + '\n')
    print(json.dumps(config), flush=True)
    server.serve_forever()
