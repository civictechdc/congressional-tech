"""Publish a verified R2 filename snapshot as static, range-readable files.

No service or credentials are needed by the browser. The document archive keeps
its source bytes; filename repacking preserves schema and ordered values.
"""
from __future__ import annotations

import argparse
from array import array
from collections import namedtuple
from dataclasses import asdict
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
from congress_api.retention.derived_files import VerifiedFile, copy_checked, custody_identity, file_identity
from congress_api.retention.viewer_inventory import PreparedManifest
from filename_resources import owned_resources
from filename_budget import DEFAULT_DECODED_POLICY, ArrowStager, DecodedBudgetExceeded, bounded_batches, failure_receipt, open_parquet
from filename_json_stream import ObservationCounts

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyarrow.parquet import ParquetFile

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

spec = importlib.util.spec_from_file_location('filename_navigation', Path(__file__).with_name('filename_navigation.py'))
navigation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(navigation)
spec = importlib.util.spec_from_file_location('filename_review_binding', Path(__file__).with_name('filename_review_binding.py'))
review_binding = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review_binding)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(root, manifest, *, validation=None):
    from congress_api.retention.catalog_publication import _manifest
    manifest = _manifest(json.dumps(manifest))
    if validation is not None:
        from congress_api.retention.catalog_validation import CatalogPairValidation
        if not isinstance(validation, CatalogPairValidation):
            raise ValueError('Invalid catalog pair validation')
        validation.require(root, manifest)
        return
    for name in ('documents', 'filenames'):
        item = manifest['files'][name]
        key = item['key']
        if not key.startswith('catalog-generations/' + manifest['generation'] + '/') or '..' in key.split('/'):
            raise ValueError('Invalid immutable catalog location.')
        path = root / key
        if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError(f'{name} differs from the R2 manifest.')
        with pq.ParquetFile(path) as file:
            if file.metadata.num_rows != item['rows'] or (file.schema_arrow.metadata or {}).get(b'catalog_id', b'').decode() != manifest['catalog_id']:
                raise ValueError('Catalog identity or row count mismatch.')


def fetch(root, *, client=None):
    import boto3
    import shutil
    import tempfile
    from congress_api.retention.catalog_publication import _manifest
    root = Path(root)
    client = client or boto3.client('s3', endpoint_url=f'https://{os.environ["CLOUDFLARE_ACCOUNT_ID"]}.r2.cloudflarestorage.com',
                          aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'],
                          aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'], region_name='auto')
    bucket = 'congressional-tech-raw'
    response = client.get_object(Bucket=bucket, Key='indexes/catalog.json')
    with owned_resources() as resources:
        stream = resources.enter_context(response['Body'])
        raw = stream.read(1024**2 + 1)
    if len(raw) > 1024**2:
        raise ValueError('Catalog selector exceeds 1 MiB read budget')
    manifest = _manifest(raw)
    modified = response['LastModified'].isoformat()
    root.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix='.catalog-fetch-', dir=root))
    try:
        for item in manifest['files'].values():
            path = staged / item['key']; path.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, item['key'], str(path))
        verify(staged, manifest)
        for item in manifest['files'].values():
            path = root / item['key']; path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(staged / item['key'], path)
            except FileExistsError:
                if path.is_symlink() or path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
                    raise ValueError('Conflicting immutable downloaded catalog: ' + item['key'])
        (root / 'indexes').mkdir(parents=True, exist_ok=True)
        temporary = root / 'indexes' / ('.catalog-' + staged.name + '.partial')
        with temporary.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        temporary.replace(root / 'indexes/catalog.json')
    except BaseException as error:
        error.add_note('Owned catalog fetch evidence retained: ' + str(staged))
        raise
    else:
        shutil.rmtree(staged)
    return modified


def write_u32(path, values):
    data = values if isinstance(values, array) and values.typecode == 'I' and sys.byteorder == 'little' else array('I', values)
    if sys.byteorder != 'little':
        data.byteswap()
    with path.open('wb') as stream:
        data.tofile(stream)



CompressionPolicy = namedtuple('CompressionPolicy', 'codec level batch_size row_group_size',
                               defaults=('zstd', 9, 8192, 8192))
DEFAULT_COMPRESSION_POLICY = CompressionPolicy()


def repack_and_verify(source, destination, policy=DEFAULT_COMPRESSION_POLICY, *, decoded_policy=DEFAULT_DECODED_POLICY, metrics=None):
    metrics = metrics if metrics is not None else {}
    try:
        with owned_resources() as owned:
            return _repack_and_verify(source, destination, policy, owned, decoded_policy, metrics)
    except DecodedBudgetExceeded as error:
        failure_receipt(destination.parent, error, decoded_policy, metrics)
        raise


def _repack_and_verify(source, destination, policy, owned, decoded_policy, metrics):
    """Repack one complete table and compare its exact schema and ordered values."""
    if policy.codec != 'zstd' or not 1 <= policy.level <= 22 or min(policy.batch_size, policy.row_group_size) < 1:
        raise ValueError('Invalid viewer compression policy.')
    # A borrowed reader keeps its original file/metadata pairing.
    if not isinstance(source, ParquetFile):
        source = owned.enter_context(open_parquet(source))
    started = time.perf_counter()
    with pq.ParquetWriter(destination, source.schema_arrow, compression=policy.codec,
                          compression_level=policy.level) as writer:
        staging = ArrowStager(writer, source.schema_arrow, row_group_size=policy.row_group_size,
                              policy=decoded_policy, metrics=metrics, stage='repack')
        for batch in bounded_batches(source, batch_rows=policy.batch_size, policy=decoded_policy,
                                     stage='repack', metrics=metrics, python_values=False):
            staging.append(batch)
        staging.flush()
    written = time.perf_counter()
    rewritten = owned.enter_context(open_parquet(destination))
    if not rewritten.schema_arrow.equals(source.schema_arrow, check_metadata=True):
        raise ValueError('Repacking changed the schema.')
    # Adaptive source/output batches may have different boundaries. Compare
    # ordered Arrow slices directly without converting either side to Python.
    before = iter(bounded_batches(source, batch_rows=policy.batch_size, policy=decoded_policy,
                                 stage='repack source verification', metrics=metrics, python_values=False))
    after = iter(bounded_batches(rewritten, batch_rows=policy.batch_size, policy=decoded_policy,
                                stage='repack output verification', metrics=metrics, python_values=False))
    left, right = next(before, None), next(after, None)
    lo = ro = 0
    while left is not None and right is not None:
        size = min(len(left) - lo, len(right) - ro)
        if not left.slice(lo, size).equals(right.slice(ro, size)):
            raise ValueError('Repacking changed catalog values.')
        lo += size; ro += size
        if lo == len(left): left, lo = next(before, None), 0
        if ro == len(right): right, ro = next(after, None), 0
    if left is not None or right is not None:
        raise ValueError('Repacking changed catalog row count.')
    return {'rows': source.metadata.num_rows, 'row_groups': rewritten.metadata.num_row_groups,
            'repack_seconds': written - started, 'equality_seconds': time.perf_counter() - written,
            'exact_equal': True}

def publish(root, target, modified=None, *, validation=None, review_identities=review_binding.IDENTITIES,
            compression_policy=DEFAULT_COMPRESSION_POLICY, stage_timings=None, stage_event=None,
            decoded_policy=DEFAULT_DECODED_POLICY, memory_metrics=None):
    memory_metrics = memory_metrics if memory_metrics is not None else {}
    try:
        with owned_resources() as owned:
            return _publish(root, target, modified, validation=validation, review_identities=review_identities,
                compression_policy=compression_policy, stage_timings=stage_timings, stage_event=stage_event, owned=owned,
                decoded_policy=decoded_policy, memory_metrics=memory_metrics)
    except DecodedBudgetExceeded as error:
        failure_receipt(target, error, decoded_policy, memory_metrics)
        raise


def publish_selected(snapshot, target, *, previous=None, read_asset=None, prior_review_binding=None,
                     review_identities=review_binding.IDENTITIES,
                     decoded_policy=DEFAULT_DECODED_POLICY, stage_timings=None,
                     stage_event=None, memory_metrics=None):
    """Prepare the maintained stable viewer directly from exact native tables."""
    from filename_native import publish_selected as prepare
    return prepare(snapshot, target, viewer=viewer, previous=previous, read_asset=read_asset,
        prior_review_binding=prior_review_binding,
        review_identities=review_identities, decoded_policy=decoded_policy,
        stage_timings=stage_timings, stage_event=stage_event, memory_metrics=memory_metrics)


def _publish(root, target, modified, *, validation, review_identities, compression_policy, stage_timings, stage_event, owned, decoded_policy, memory_metrics):
    target = Path(target)
    if target.exists() and (not target.is_dir() or target.is_symlink() or any(target.iterdir())):
        raise ValueError('Viewer output must be a fresh empty directory; choose a new target to retry the build.')
    timings = stage_timings if stage_timings is not None else {}
    started = time.perf_counter()
    last_stage = started
    def stage(name, next_stage=None):
        nonlocal last_stage
        now = time.perf_counter()
        timings[name] = now - last_stage
        last_stage = now
        if stage_event:
            stage_event({'event': 'stage_completed', 'stage': name, 'seconds': timings[name]})
            if next_stage:
                stage_event({'event': 'stage_started', 'stage': next_stage})
    if stage_event:
        stage_event({'event': 'stage_started', 'stage': 'input_verification'})
    manifest = json.loads((root / 'indexes/catalog.json').read_text())
    document_item = manifest['files']['documents']
    document_path = root / document_item['key']
    document_custody = custody_identity(document_path)
    verify(root, manifest, validation=validation)
    stage('input_verification', 'catalog_loading')
    catalog = owned.enter_context(viewer.Catalog(root / manifest['files']['filenames']['key'], search_indexes=False))
    stage('catalog_loading', 'documents_preparation')
    target.mkdir(parents=True, exist_ok=True)
    # Generation-specific paths prevent a stale tab from mixing data from
    # different snapshots. Removed files fail visibly and require a reload.
    output = target / manifest['generation'] / 'viewer-v2'
    output.mkdir(parents=True, exist_ok=False)
    files = {}
    file_proofs = {}

    def describe(name, path, rows=None, *, proof=None):
        if proof is None:
            proof = file_identity(path)
        elif not isinstance(proof, VerifiedFile):
            raise ValueError('Describing a copied file requires its issued destination proof')
        proof.require(path)
        relative = str(path.relative_to(target))
        file_proofs[relative] = proof
        files[name] = dict(path=relative, **proof)
        if rows is not None:
            files[name]['rows'] = rows

    # Documents are an archive download, not a browser decoding input. Preserve
    # their verified bytes without requiring a giant source row to fit a decoder.
    document_file = catalog.document_file
    if (catalog.document_path.resolve() != document_path.resolve()
            or custody_identity(document_path) != document_custody
            or document_file.metadata.num_rows != document_item['rows']
            or (document_file.schema_arrow.metadata or {}).get(b'catalog_id', b'').decode() != manifest['catalog_id']):
        raise ValueError('Document archive source custody or catalog identity changed')
    path = output / 'documents.parquet'
    copy_started = time.perf_counter()
    with document_path.open('rb') as stream:
        proof = copy_checked(stream, path, size=document_item['bytes'], expected=document_item, key=document_item['key'])
    if custody_identity(document_path) != document_custody:
        raise ValueError('Document archive source custody changed during copy')
    describe('documents', path, document_file.metadata.num_rows, proof=proof)
    files['documents']['encoding'] = dict(mode='source_passthrough', source_sha256=document_item['sha256'])
    timings['documents_copy'] = dict(rows=document_file.metadata.num_rows, **proof,
        copy_seconds=time.perf_counter() - copy_started, verification_method='complete_sha256_bytes')
    stage('documents_preparation', 'filenames_preparation')
    print(f"documents: {proof['bytes']:,} bytes; complete source SHA-256/bytes verified", flush=True)

    path = output / 'filenames.parquet'
    result = repack_and_verify(catalog.file, path, compression_policy,
        decoded_policy=decoded_policy, metrics=memory_metrics)
    timings['filenames_repack'] = result
    describe('filenames', path, result['rows'])
    stage('filenames_preparation', 'observations')
    print(f'filenames: {path.stat().st_size:,} bytes; all values verified', flush=True)

    source = catalog.file
    counts = owned.enter_context(ObservationCounts(source))
    observations.publish_observations(source, output, counts=counts, policy=decoded_policy, metrics=memory_metrics)
    for name, filename in [('observations', 'observations.bin'), ('observation_rows', 'observation-rows.bin'), ('observation_index', 'observation-index.json')]:
        describe(name, output / filename)
    print('Source observations: every reconstructed value verified', flush=True)
    stage('observations', 'details')
    document_file = catalog.document_file
    detail_path = output / 'details.parquet'
    detail_info = details.publish_details(source, detail_path, observation_counts=counts, policy=decoded_policy, metrics=memory_metrics)
    describe('details', detail_path, detail_info['rows'])

    stage('details', 'navigation')
    order = catalog.order.to_pylist()
    position = catalog.entry_positions
    # Group positions always refer to browse.parquet's filename-sorted rows.
    group = array('I', (position[value] for value in catalog.entry_ids))
    preferred = array('I', (catalog.preferred_sources[value] for value in order))
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
    for name, path in navigation.publish_navigation(group, preferred, output).items():
        describe(name, path)
    path = output / 'flags.bin'
    path.write_bytes(flags)
    describe('flags', path)

    stage('navigation', 'review_binding')
    # Reviews are published once; their positions are recomputed for every
    # catalog version from stable identities, so they survive rebuilds.
    if review_identities and (identities := review_binding.load_identities(review_identities)) is not None:
        binding = review_binding.bind(catalog, identities)
        path = output / 'review-binding.json'
        path.write_text(json.dumps(binding, sort_keys=True, separators=(',', ':')) + '\n')
        describe('review_binding', path)
        print(f"Review binding: {len(binding['rows'])} bound, {len(binding['withdrawn'])} withdrawn", flush=True)

    stage('review_binding', 'browse')
    # IDs are resolved when a row is opened; carrying both hashes on every
    # list row would duplicate tens of megabytes without displaying them.
    browse = catalog.documents.drop([name for name in ['body_key', 'source_id', 'document_id', 'extension', 'recovered_filename', 'response_result'] if name in catalog.documents.column_names]).take(catalog.order)
    basis = document_file.read(columns=['document_kind_source']).take(catalog.order) if 'document_kind_source' in document_file.schema_arrow.names else pa.table({'document_kind_source': pa.nulls(len(browse), type=pa.list_(pa.string()))})
    browse = browse.append_column('document_kind_source', basis.column(0))
    browse = browse.append_column('source_count', pa.array([len(catalog.members[value]) for value in order], type=pa.uint32()))
    browse = browse.append_column('retained', pa.array([bool(catalog.saved_responses[value]) for value in order]))
    path = output / 'browse.parquet'
    pq.write_table(browse, path, row_group_size=1024, compression='zstd', compression_level=9)
    describe('browse', path, len(browse))

    stage('browse', 'ids')
    # Stable source IDs resolve through one small binary prefix file, instead
    # of loading a million 64-character IDs into browser memory.
    ids = output / 'ids'
    ids.mkdir(exist_ok=True)
    with ExitStack() as streams:
        shard_streams = [streams.enter_context((ids / f'{prefix:02x}.bin').open('wb')) for prefix in range(256)]
        for identity, index in catalog.source_ids.items():
            raw = bytes.fromhex(identity)
            if len(raw) != 32:
                raise ValueError('Expected a SHA-256 source ID.')
            shard_streams[raw[0]].write(raw + struct.pack('<I', index))
    for prefix in range(256):
        path = ids / f'{prefix:02x}.bin'
        file_proofs[str(path.relative_to(target))] = file_identity(path)

    stage('ids', 'manifest')
    info = dict(catalog.info, generation=manifest['generation'], remote_last_modified=modified or catalog.info.get('remote_last_modified'))
    info.pop('synced_at', None)
    publication = dict(version=5, published_at=datetime.now(timezone.utc).isoformat(), info=info, files=files,
                       source_manifest=manifest, ids=str(ids.relative_to(target)) + '/',
                       compression_policy=dict(compression_policy._asdict(), applies_to=['filenames']))
    (target / 'manifest.json').write_text(json.dumps(publication, ensure_ascii=False, separators=(',', ':')))
    print(f'Publication: {sum(p.stat().st_size for p in target.rglob("*") if p.is_file()):,} bytes', flush=True)
    stage('manifest')
    timings['total_seconds'] = time.perf_counter() - started
    timings['decoded_memory'] = {'policy': asdict(decoded_policy), 'observed': dict(memory_metrics)}
    file_proofs['manifest.json'] = file_identity(target / 'manifest.json')
    return PreparedManifest(publication, file_proofs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / '.cache/filename-viewer-publication')
    parser.add_argument('--output', type=Path, default=ROOT / 'apps/site/public/data/filenames')
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--compression-level', type=int, choices=(3, 9, 19), default=DEFAULT_COMPRESSION_POLICY.level,
                        help='Viewer Zstandard compression level (maintained default: 9).')
    args = parser.parse_args()
    publish(args.source, args.output, fetch(args.source) if args.fetch else None,
            compression_policy=DEFAULT_COMPRESSION_POLICY._replace(level=args.compression_level))
