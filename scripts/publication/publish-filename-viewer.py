"""Prepare native viewer output and retain shared verified-file utilities.

No service or credentials are needed by the browser. The document archive keeps
its source bytes; filename repacking preserves schema and ordered values.
"""
from __future__ import annotations

from array import array
import time

from viewer_publication.filename_compression import CompressionPolicy, DEFAULT_COMPRESSION_POLICY, validate_compression
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
from congress_api.retention.derived_files import VerifiedFile, copy_checked, custody_identity, file_identity
from viewer_publication.filename_resources import owned_resources
from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY, ArrowStager, DecodedBudgetExceeded, bounded_batches, failure_receipt, open_parquet

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pyarrow.parquet import ParquetFile

ROOT = Path(__file__).resolve().parents[2]
import viewer_publication.filename_viewer as viewer
import viewer_publication.filename_observations as observations
import viewer_publication.filename_details as details
import viewer_publication.filename_navigation as navigation
import viewer_publication.filename_review_binding as review_binding


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
    validate_compression(policy)
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


def publish_selected(snapshot, target, *, previous=None, read_asset=None, prior_review_binding=None,
                     compression_policy=DEFAULT_COMPRESSION_POLICY, renderer_upgrade=False, resume_upgrade=False,
                     review_identities=review_binding.IDENTITIES,
                     decoded_policy=DEFAULT_DECODED_POLICY, stage_timings=None,
                     stage_event=None, memory_metrics=None):
    """Prepare the maintained stable viewer directly from exact native tables."""
    from viewer_publication.filename_native import publish_selected as prepare
    return prepare(snapshot, target, viewer=viewer, previous=previous, read_asset=read_asset,
        prior_review_binding=prior_review_binding, compression_policy=compression_policy,
        renderer_upgrade=renderer_upgrade, resume_upgrade=resume_upgrade, review_identities=review_identities, decoded_policy=decoded_policy,
        stage_timings=stage_timings, stage_event=stage_event, memory_metrics=memory_metrics)


if __name__ == '__main__':
    raise SystemExit('Direct viewer generation is retired; use publish-viewer-r2.py prepare with explicit native storage.')
