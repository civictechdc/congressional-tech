"""Publish a verified R2 filename snapshot as static, range-readable files.

No service or credentials are needed by the browser. Repacking preserves the
Arrow schema and row order; small derived indexes only accelerate navigation.
"""
from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
VIEWER = ROOT / 'docs/youtube-coverage/research/scripts/view_document_filenames.py'
spec = importlib.util.spec_from_file_location('filename_viewer', VIEWER)
viewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(viewer)
spec = importlib.util.spec_from_file_location('filename_observations', Path(__file__).with_name('filename_observations.py'))
observations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observations)
spec = importlib.util.spec_from_file_location('filename_details', Path(__file__).with_name('filename_details.py'))
details = importlib.util.module_from_spec(spec)
spec.loader.exec_module(details)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(root, manifest):
    if manifest.get('version') != 1 or not re.fullmatch(r'[a-f0-9]{32}', manifest.get('generation', '')):
        raise ValueError('Unsupported catalog manifest.')
    for name in ('documents', 'filenames'):
        item = manifest['files'][name]
        key = item['key']
        if not key.startswith('catalog-generations/' + manifest['generation'] + '/') or '..' in key.split('/'):
            raise ValueError('Invalid immutable catalog location.')
        path = root / key
        if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError(f'{name} differs from the R2 manifest.')
        file = pq.ParquetFile(path)
        if file.metadata.num_rows != item['rows'] or (file.schema_arrow.metadata or {}).get(b'catalog_id', b'').decode() != manifest['catalog_id']:
            raise ValueError('Catalog identity or row count mismatch.')


def fetch(root):
    import boto3
    client = boto3.client('s3', endpoint_url=f'https://{os.environ["CLOUDFLARE_ACCOUNT_ID"]}.r2.cloudflarestorage.com',
                          aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
                          aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto')
    bucket = 'congressional-tech-raw'
    response = client.get_object(Bucket=bucket, Key='indexes/catalog.json')
    manifest = json.loads(response['Body'].read())
    modified = response['LastModified'].isoformat()
    if not re.fullmatch(r'[a-f0-9]{32}', manifest.get('generation', '')):
        raise ValueError('Invalid catalog generation.')
    for item in manifest['files'].values():
        key = item['key']
        if not key.startswith('catalog-generations/' + manifest['generation'] + '/') or '..' in key.split('/'):
            raise ValueError('Invalid catalog path.')
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        client.download_file(bucket, key, str(path))
    (root / 'indexes').mkdir(parents=True, exist_ok=True)
    (root / 'indexes/catalog.json').write_text(json.dumps(manifest))
    return modified


def write_u32(path, values):
    data = array('I', values)
    if sys.byteorder != 'little':
        data.byteswap()
    path.write_bytes(data.tobytes())


def publish(root, target, modified=None):
    manifest = json.loads((root / 'indexes/catalog.json').read_text())
    verify(root, manifest)
    catalog = viewer.Catalog(root / manifest['files']['filenames']['key'])
    target.mkdir(parents=True, exist_ok=True)
    # Generation-specific paths prevent a stale tab from mixing data from
    # different snapshots. Removed files fail visibly and require a reload.
    output = target / manifest['generation'] / 'viewer-v2'
    output.mkdir(parents=True, exist_ok=True)
    files = {}

    def describe(name, path, rows=None):
        files[name] = dict(path=str(path.relative_to(target)), bytes=path.stat().st_size, sha256=digest(path))
        if rows is not None:
            files[name]['rows'] = rows

    for name in ('documents', 'filenames'):
        source = pq.ParquetFile(root / manifest['files'][name]['key'])
        path = output / f'{name}.parquet'
        with pq.ParquetWriter(path, source.schema_arrow, compression='zstd', compression_level=19) as writer:
            for batch in source.iter_batches(batch_size=8192):
                table = pa.Table.from_batches([batch], schema=source.schema_arrow)
                writer.write_table(table, row_group_size=8192)
        # Compare every value after rewriting; hashes identify the published
        # bytes while this check establishes equality with the original data.
        rewritten = pq.ParquetFile(path)
        if not rewritten.schema_arrow.equals(source.schema_arrow, check_metadata=True):
            raise ValueError('Repacking changed the schema.')
        for before, after in zip(source.iter_batches(batch_size=8192), rewritten.iter_batches(batch_size=8192), strict=True):
            if not before.equals(after):
                raise ValueError('Repacking changed catalog values.')
        describe(name, path, source.metadata.num_rows)
        print(f'{name}: {path.stat().st_size:,} bytes; all values verified', flush=True)

    source = pq.ParquetFile(root / manifest['files']['filenames']['key'])
    observations.publish_observations(source, output)
    for name, filename in [('observations', 'observations.bin'), ('observation_rows', 'observation-rows.bin'), ('observation_index', 'observation-index.json')]:
        describe(name, output / filename)
    print('Source observations: every reconstructed value verified', flush=True)
    document_file = pq.ParquetFile(root / manifest['files']['documents']['key'])
    detail_path = output / 'details.parquet'
    detail_info = details.publish_details(source, detail_path)
    describe('details', detail_path, detail_info['rows'])

    order = catalog.order.to_pylist()
    position = [0] * len(order)
    for index, original in enumerate(order):
        position[original] = index
    # Group positions always refer to browse.parquet's filename-sorted rows.
    group = [position[value] for value in catalog.entry_ids]
    preferred = [catalog.preferred_sources[value] for value in order]
    flags = bytes((1 if catalog.saved_responses[value] else 0) |
                  (2 if value in catalog.document_entries else 0) |
                  (4 if not catalog.documents['document_kind'][value].as_py() else 0) |
                  (8 if not catalog.documents['document_family'][value].as_py() else 0) |
                  (16 if value in catalog.api_entries else 0) |
                  (32 if value in catalog.video_entries else 0) for value in order)
    for name, values in [('groups', group), ('preferred', preferred)]:
        path = output / f'{name}.bin'
        write_u32(path, values)
        describe(name, path)
    path = output / 'flags.bin'
    path.write_bytes(flags)
    describe('flags', path)

    # IDs are resolved when a row is opened; carrying both hashes on every
    # list row would duplicate tens of megabytes without displaying them.
    browse = catalog.documents.take(catalog.order).drop([name for name in ['body_key', 'source_id', 'document_id', 'extension', 'recovered_filename', 'response_result'] if name in catalog.documents.column_names])
    basis = document_file.read(columns=['document_kind_source']).take(catalog.order) if 'document_kind_source' in document_file.schema_arrow.names else pa.table({'document_kind_source': pa.nulls(len(browse), type=pa.list_(pa.string()))})
    browse = browse.append_column('document_kind_source', basis.column(0))
    browse = browse.append_column('source_count', pa.array([len(catalog.members[value]) for value in order], type=pa.uint32()))
    browse = browse.append_column('retained', pa.array([bool(catalog.saved_responses[value]) for value in order]))
    path = output / 'browse.parquet'
    pq.write_table(browse, path, row_group_size=1024, compression='zstd', compression_level=9)
    describe('browse', path, len(browse))

    # Stable source IDs resolve through one small binary prefix file, instead
    # of loading a million 64-character IDs into browser memory.
    ids = output / 'ids'
    ids.mkdir(exist_ok=True)
    shards = [bytearray() for _ in range(256)]
    for identity, index in catalog.source_ids.items():
        raw = bytes.fromhex(identity)
        if len(raw) != 32:
            raise ValueError('Expected a SHA-256 source ID.')
        shards[raw[0]].extend(raw + struct.pack('<I', index))
    for prefix, data in enumerate(shards):
        (ids / f'{prefix:02x}.bin').write_bytes(data)

    info = dict(catalog.info, generation=manifest['generation'], remote_last_modified=modified or catalog.info.get('remote_last_modified'))
    info.pop('synced_at', None)
    publication = dict(version=5, published_at=datetime.now(timezone.utc).isoformat(), info=info, files=files,
                       source_manifest=manifest, ids=str(ids.relative_to(target)) + '/')
    (target / 'manifest.json').write_text(json.dumps(publication, ensure_ascii=False, separators=(',', ':')))
    print(f'Publication: {sum(p.stat().st_size for p in target.rglob("*") if p.is_file()):,} bytes', flush=True)
    return publication


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / '.cache/filename-viewer-publication')
    parser.add_argument('--output', type=Path, default=ROOT / 'apps/site/public/data/filenames')
    parser.add_argument('--fetch', action='store_true')
    args = parser.parse_args()
    publish(args.source, args.output, fetch(args.source) if args.fetch else None)
