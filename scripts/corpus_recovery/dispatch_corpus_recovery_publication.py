"""Explicit publication and continuation of an imported recovery batch; no acquisition or raw writes.

Requires an actual completed import. Default mode verifies local evidence only.
The maintained catalog and viewer implementations are loaded from --runtime.
"""
import argparse
import configparser
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cloud_clear():
    from corpus_recovery.guards import active_cloud_writers
    active_cloud_writers()


def verify_import(batch, imported, *, readiness=None):
    from corpus_recovery.admission import verify_import as verify
    return verify(batch, imported, readiness=readiness)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def publication_conditions(continuation):
    """Persist the first publication conditions separately from advancing versions."""
    conditions = continuation.value.get('publication_inputs')
    if conditions is None:
        conditions = {'previous_etag': continuation.value['versions']['viewer-publications/manifest.json'],
                      'selected_etag': continuation.value['versions']['indexes/catalog.json']}
        continuation.value['publication_inputs'] = conditions
        continuation.flush()
    if (not isinstance(conditions, dict) or set(conditions) != {'previous_etag','selected_etag'}
            or not isinstance(conditions['selected_etag'], str) or not conditions['selected_etag']
            or (conditions['previous_etag'] is not None and not isinstance(conditions['previous_etag'],str))):
        raise ValueError('Malformed original local publication conditions')
    return conditions


def run(args):
    batch, imported, runtime = args.batch.resolve(), args.imported.resolve(), args.runtime.resolve()
    if getattr(args, 'resume', False) and not args.execute:
        raise ValueError('--resume requires --execute')
    readiness = getattr(args, 'readiness', None)
    result = verify_import(batch, imported, readiness=readiness)
    if not args.execute:
        return dict(local_preflight=True, import_verified=True, writes=False)
    cloud_clear()
    control_root = (getattr(args, 'control_root', None) or ROOT).resolve()
    lock_path = control_root / '.cache/local-recovery.lock'
    lock = lock_path.open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    destination = args.destination.resolve()
    parent = os.getppid()
    from viewer_publication.continuation import Continuation
    from corpus_recovery.guards import RecoveryGuard
    def report(name, value):
        continuation.save(name, (json.dumps(value, indent=2) + '\n').encode())
    def journal(event, value):
        continuation.record(event, value)
        with (destination / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), event=event, value=value))+'\n')
            stream.flush(); os.fsync(stream.fileno())
    paths = [p for folder in ['packages/congress_api/src', 'packages/house-naming/src',
                'apps/site/scripts', 'docs/youtube-coverage/research/scripts']
             for p in (runtime / folder).rglob('*') if p.is_file() and '__pycache__' not in str(p)]
    paths += list(batch.glob('*.json')) + list((ROOT/'scripts/corpus_recovery').glob('*.py'))
    import corpus_recovery
    import corpus_recovery.inventory as inventory_module
    import corpus_recovery.acknowledge as acknowledgment_module
    import corpus_recovery.admission as admission_module
    import corpus_recovery.guards as recovery_guard_module
    import corpus_recovery.mappings as mapping_module
    import viewer_publication.client as publication_client
    import viewer_publication.continuation as publication_continuation
    paths += [Path(corpus_recovery.__file__).resolve(),
              Path(inventory_module.__file__).resolve(),
              Path(publication_client.__file__).resolve(),
              Path(publication_continuation.__file__).resolve(),
              Path(acknowledgment_module.__file__).resolve(),
              Path(recovery_guard_module.__file__).resolve(),
              Path(admission_module.__file__).resolve(),
              Path(mapping_module.__file__).resolve(),
              args.baseline.resolve(), args.config.resolve(),
              imported/'payloads/import-complete.json', imported/'events.jsonl']
    paths += [imported/'payloads'/key for key in ('indexes/captures.parquet', 'indexes/download-state.parquet')]
    if readiness is not None:
        paths += [readiness.resolve()]
        body_readback = readiness.resolve().with_name('remote-body-readback.json')
        if body_readback.exists(): paths += [body_readback]
    pins = {str(p): digest(p) for p in paths}
    binding = dict(pins=pins, batch=str(batch), imported=str(imported), runtime=str(runtime),
                   baseline=str(args.baseline.resolve()), control_root=str(control_root))
    continuation = Continuation(destination, binding, resume=getattr(args, 'resume', False))
    save = continuation.save
    report('pins.json', pins)
    for package in ['congress_api', 'house-naming']:
        sys.path.insert(0, str(runtime/'packages'/package/'src'))
    sys.path.insert(0, str(runtime/'apps/site/scripts'))
    import boto3
    from botocore.config import Config
    from congress_api.retention.r2 import R2Store
    from congress_api.retention.catalog_staging import WorkingCatalog
    from congress_api.cli.raw_progress import ProgressLog
    from congress_api.retention.document_index import validate_document_indexes
    from congress_api.retention.catalog_validation import validate_catalog_pair
    from congress_api.retention.raw_catalog import rebuild_catalog_in_directory
    from filename_recoveries import accepted_rows
    from viewer_publication.client import ContinuedPublicationClient
    from corpus_recovery.mappings import publish_mappings
    config = configparser.ConfigParser(); config.read(args.config); account = config['congressionalraw']
    client = boto3.client('s3', endpoint_url=account['endpoint'], region_name='auto',
        aws_access_key_id=account['access_key_id'], aws_secret_access_key=account['secret_access_key'],
        config=Config(connect_timeout=15, read_timeout=180, retries={'total_max_attempts': 1},
                      request_checksum_calculation='when_required', response_checksum_validation='when_required'))
    bucket = 'congressional-tech-raw'
    protected = ['indexes/captures.parquet', 'indexes/download-state.parquet', 'indexes/catalog.json',
                 'viewer-publications/recoveries/accepted.json', 'viewer-publications/manifest.json']
    versions = continuation.value['versions']
    if not versions:
        baseline_versions = {}
        for key in protected:
            response = client.get_object(Bucket=bucket, Key=key)
            with response['Body'] as stream: raw = stream.read()
            if len(raw) != response['ContentLength']: raise ValueError('Incomplete publication baseline')
            save('baseline/'+key, raw); baseline_versions[key] = response['ETag']
            if key in protected[:2] and raw != (imported/'payloads'/key).read_bytes():
                raise ValueError('Raw indexes changed since completed import; reconcile before publication')
        versions.update(baseline_versions)
        continuation.flush()
    if getattr(args, 'resume', False):
        continuation.reconcile(client, bucket)
    def local_check():
        if os.getppid() != parent or shutil.disk_usage(destination).free < 12*1024**3:
            raise RuntimeError('Publication parent or disk reserve changed')
        held, named = os.fstat(lock.fileno()), lock_path.stat()
        if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino): raise RuntimeError('Lock replaced')
    def protected_check():
        for key, version in versions.items():
            if client.head_object(Bucket=bucket, Key=key)['ETag'] != version:
                raise RuntimeError('Publication input changed: '+key)
    guard = RecoveryGuard(pins=pins, local_check=local_check, cloud_check=cloud_clear,
                          protected_check=protected_check)
    def after_write(key, version):
        if key in versions:
            versions[key] = version
            continuation.flush()
    proxy = ContinuedPublicationClient(client, continuation=continuation, guard=guard, journal=journal, after_write=after_write)
    source = destination/'source'; expected = set(json.loads((batch/'bodies.json').read_text()))
    pair_validation = None
    content_validation = None
    def validate_pair(manifest):
        nonlocal pair_validation
        if pair_validation is not None:
            return pair_validation.require(source, manifest, validator=validate_document_indexes, expected_bodies=expected)
        pair_validation = validate_catalog_pair(source, manifest, validator=validate_document_indexes,
                                               expected_bodies=expected, references=content_validation)
        return pair_validation.coverage
    class Store(R2Store):
        def accept_catalog_validation(self, validation):
            nonlocal content_validation
            content_validation = validation
        def read(self, key):
            body = super().read(key)
            if body is not None and key == 'indexes/catalog.json':
                save('source/'+key, body, replace=key == 'indexes/catalog.json')
            return body
        def put(self, key, body, *, immutable=False):
            if key == 'indexes/catalog.json':
                save('proposed/'+key, body, replace=True)
            result = super().put(key, body, immutable=immutable)
            if key == 'indexes/catalog.json':
                save('source/'+key, body, replace=True)
            return result
        def save_derived(self, key, path, identity):
            from congress_api.retention.derived_files import retain_verified_file
            return retain_verified_file(path, source / key, expected=identity, key=key)
        def read_derived_file(self, key, path, *, expected=None):
            identity = super().read_derived_file(key, path, expected=expected)
            if identity is not None:
                self.save_derived(key, path, identity)
            return identity
        def put_derived_file(self, key, path, *, expected):
            self.save_derived(key, path, expected)
            return super().put_derived_file(key, path, expected=expected)
        def put_catalog_manifest(self, data, *, expected_version):
            manifest = json.loads(data)
            coverage = validate_pair(manifest)
            report('coverage.json', coverage)
            return super().put_catalog_manifest(data, expected_version=expected_version)
    try:
        guard.boundary()
        def catalog_phase():
            build = destination/'build'
            # An unaccepted build may contain the only diagnostic SQLite state.
            # Explicit continuation reuses accepted phases; it never deletes or
            # silently restarts incomplete catalog work.
            if build.exists():
                raise RuntimeError('Incomplete catalog build retained; reconcile before continuation: '+str(build))
            build.mkdir(); (build/'indexes').mkdir()
            working = WorkingCatalog(build/'working.sqlite')
            try:
                with ProgressLog(destination/'catalog-progress.json'):
                    catalog = rebuild_catalog_in_directory(Store(proxy,bucket), working=working, root=build)
            finally: working.close()
            manifest = json.loads((source/'indexes/catalog.json').read_text())
            coverage = validate_pair(manifest)
            report('coverage.json', coverage)
            return catalog
        catalog = continuation.phase('catalog', catalog_phase,
            files=lambda: [*source.rglob('*parquet'), source/'indexes/catalog.json', destination/'coverage.json'])
        report('catalog-result.json', catalog)
        guard.boundary()
        def mapping_phase():
            mapping = publish_mappings(proxy, bucket=bucket,
                baseline=json.loads(args.baseline.read_text()), prepared=json.loads((batch/'accepted.json').read_text()),
                validate=accepted_rows, guard=guard.boundary, save_payload=save, journal=journal)
            return mapping
        mapping = continuation.phase('mappings', mapping_phase, files=lambda: [p for p in (destination/'accepted-proposed.json', destination/'accepted-before.json') if p.exists()])
        report('mapping-result.json', mapping)
        guard.boundary()
        def prepared_phase():
            builder = load(runtime/'apps/site/scripts/publish-filename-viewer.py', 'recovery_viewer_builder')
            validate_pair(json.loads((source/'indexes/catalog.json').read_text()))
            selected_metadata = client.head_object(Bucket=bucket, Key='indexes/catalog.json')
            if selected_metadata['ETag'] != versions['indexes/catalog.json']:
                raise ValueError('Selected catalog changed before accepted viewer preparation')
            modified = selected_metadata.get('LastModified')
            return builder.publish(source, destination/'prepared', modified.isoformat() if modified else None, validation=pair_validation)
        continuation.phase('prepared', prepared_phase,
            files=lambda: [p for p in (destination/'prepared').rglob('*') if p.is_file()])
        guard.boundary()
        def publication_phase():
            publisher = load(runtime/'apps/site/scripts/publish-viewer-r2.py', 'recovery_viewer_publisher')
            if 'release_plan' not in continuation.value:
                import uuid
                continuation.value['release_plan'] = dict(release='releases/'+uuid.uuid4().hex+'/',
                    published_at=datetime.now(timezone.utc).isoformat())
                continuation.flush()
            prepared_root = destination/'prepared'
            manifest = json.loads((prepared_root/'manifest.json').read_text())
            publication = publisher.upload(proxy, prepared_root, manifest,
                **publication_conditions(continuation), publication_plan=continuation.value['release_plan'])
            if publication['status'] not in {'published', 'unchanged'}:
                raise ValueError('Viewer was not published')
            return publication
        publication = continuation.phase('publication', publication_phase, files=lambda: [])
        guard.boundary()
        report('complete.json', dict(complete=True, catalog=catalog, mapping=mapping,
                                    publication=publication, imported=result))
        return publication
    except BaseException as error:
        journal('publication_failed_requires_reconciliation', dict(error_type=type(error).__name__, error=str(error)))
        raise
    finally: lock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['batch','imported','runtime','baseline','destination']:
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--control-root', type=Path, default=ROOT, help='Shared checkout owning the recovery lock across runtimes.')
    parser.add_argument('--config', type=Path, default=ROOT/'.cache/r2-admin/rclone.conf')
    parser.add_argument('--readiness', type=Path, help='Reconciled readiness evidence pinned by the completed import.')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Explicitly reconcile and continue this destination; requires --execute.')
    print(json.dumps(run(parser.parse_args()), indent=2))
