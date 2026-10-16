"""One-shot publication of an imported recovery batch; no acquisition or raw writes.

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

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cloud_clear():
    pages = json.loads(subprocess.check_output(['gh', 'api', '--paginate', '--slurp',
        'repos/civictechdc/congressional-tech/actions/workflows/capture-raw-sources.yml/runs?per_page=100'],
        text=True, timeout=60))
    active = [r['id'] for p in pages for r in p['workflow_runs']
              if r['event'] != 'push' and r['status'] != 'completed']
    if active:
        raise RuntimeError(f'Cloud capture writer active: {active}')


def verify_import(batch, imported):
    manifest = json.loads((batch / 'manifest.json').read_text())
    ready = json.loads((batch / 'import-readiness.json').read_text())
    for name, expected in ready['files'].items():
        if name in manifest['files'] and manifest['files'][name] != expected:
            raise ValueError('Conflicting batch evidence hashes')
    for name, expected in (manifest['files'] | ready['files']).items():
        if Path(name).name != name or digest(batch / name) != expected:
            raise ValueError('Batch evidence changed: ' + name)
    preparation = json.loads((batch / 'source-record-preparation.json').read_text())
    if preparation['unresolved'] or preparation['batch_manifest_sha256'] != digest(batch / 'manifest.json'):
        raise ValueError('Source records do not cover the sealed batch')
    result = json.loads((imported / 'payloads/import-complete.json').read_text())
    events = [json.loads(line) for line in (imported / 'events.jsonl').read_text().splitlines()]
    completed = [e['value'] for e in events if e['event'] == 'import_complete']
    if (not result.get('complete') or completed != [result]
            or result['added_capture_rows'] != ready['capture_rows']
            or result['distinct_bodies'] != ready['distinct_capture_bodykeys']):
        raise ValueError('Import completion does not cover the sealed batch')
    pins = next(e['value'] for e in events if e['event'] == 'pins')
    for name in ['manifest.json', 'prepared-source-records.json', 'import-readiness.json']:
        if pins.get(str(batch / name)) != digest(batch / name):
            raise ValueError('Import belongs to a different batch')
    return result


def verify_coverage(root, manifest, expected):
    import pyarrow.parquet as pq
    found = set()
    for label, filename in [('filenames', 'document-filenames.parquet'), ('documents', 'documents.parquet')]:
        item = manifest['files'][label]
        if item['key'] != f"catalog-generations/{manifest['generation']}/{filename}":
            raise ValueError('Unexpected catalog pair path')
        path = root / item['key']
        if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Catalog pair bytes differ')
        table = pq.ParquetFile(path)
        if ((table.schema_arrow.metadata or {}).get(b'catalog_id', b'').decode() != manifest['catalog_id']
                or table.metadata.num_rows != item['rows']):
            raise ValueError('Catalog pair identity differs')
        if label == 'filenames':
            for part in table.iter_batches(columns=['body_key']):
                found.update(x for x in part.column(0).to_pylist() if x)
    missing = set(expected) - found
    if missing:
        raise ValueError(f'Imported recovery bodies absent from catalog: {len(missing)}')
    return dict(expected_bodies=len(expected), missing_bodies=0, catalog_id=manifest['catalog_id'])


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rebuild_retained_catalog(store, *, working, root):
    """Apply the maintained public wrapper's input normalization to durable builds."""
    from congress_api.retention.raw_catalog import _rebuild_catalog
    from congress_api.retention.document_index import validated_body_readings
    return _rebuild_catalog(store, None, seeds=(), workers=4, repair=False,
                            inspect_bodies=False, working=working, root=root,
                            body_readings=validated_body_readings(()))


def run(args):
    batch, imported, runtime = args.batch.resolve(), args.imported.resolve(), args.runtime.resolve()
    result = verify_import(batch, imported)
    if not args.execute:
        return dict(local_preflight=True, import_verified=True, writes=False)
    cloud_clear()
    lock = (ROOT / '.cache/local-recovery.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    parent = os.getppid()
    def save(name, raw):
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    def report(name, value):
        save(name, (json.dumps(value, indent=2) + '\n').encode())
    def journal(event, value):
        with (destination / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), event=event, value=value))+'\n')
            stream.flush(); os.fsync(stream.fileno())
    paths = [p for folder in ['packages/congress_api/src', 'packages/house-naming/src',
                'apps/site/scripts', 'docs/youtube-coverage/research/scripts']
             for p in (runtime / folder).rglob('*') if p.is_file() and '__pycache__' not in str(p)]
    paths += list(batch.glob('*.json')) + list((ROOT/'scripts').glob('*corpus_recovery*.py'))
    paths += [ROOT/'scripts/guarded_recovery_publication_client.py', args.baseline.resolve()]
    pins = {str(p): digest(p) for p in paths}
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
    from filename_recoveries import accepted_rows
    from guarded_recovery_publication_client import GuardedPublicationClient
    from publish_corpus_recovery_mappings import publish_mappings
    config = configparser.ConfigParser(); config.read(args.config); account = config['congressionalraw']
    client = boto3.client('s3', endpoint_url=account['endpoint'], region_name='auto',
        aws_access_key_id=account['access_key_id'], aws_secret_access_key=account['secret_access_key'],
        config=Config(connect_timeout=15, read_timeout=180, retries={'total_max_attempts': 1},
                      request_checksum_calculation='when_required', response_checksum_validation='when_required'))
    bucket = 'congressional-tech-raw'
    protected = ['indexes/captures.parquet', 'indexes/download-state.parquet', 'indexes/catalog.json',
                 'viewer-publications/recoveries/accepted.json', 'viewer-publications/manifest.json']
    versions = {}
    for key in protected:
        response = client.get_object(Bucket=bucket, Key=key)
        with response['Body'] as stream: raw = stream.read()
        if len(raw) != response['ContentLength']: raise ValueError('Incomplete publication baseline')
        save('baseline/'+key, raw); versions[key] = response['ETag']
        if key in protected[:2] and raw != (imported/'payloads'/key).read_bytes():
            raise ValueError('Raw indexes changed since completed import; reconcile before publication')
    def guard():
        cloud_clear()
        if os.getppid() != parent or shutil.disk_usage(destination).free < 12*1024**3:
            raise RuntimeError('Publication parent or disk reserve changed')
        held, named = os.fstat(lock.fileno()), (ROOT/'.cache/local-recovery.lock').stat()
        if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino): raise RuntimeError('Lock replaced')
        if any(digest(p) != h for p,h in pins.items()): raise RuntimeError('Publication pin changed')
        for key, version in versions.items():
            if client.head_object(Bucket=bucket, Key=key)['ETag'] != version:
                raise RuntimeError('Publication input changed: '+key)
    def after_write(key, version):
        if key in versions: versions[key] = version
    proxy = GuardedPublicationClient(client, guard=guard, journal=journal, after_write=after_write)
    source = destination/'source'; expected = set(json.loads((batch/'bodies.json').read_text()))
    class Store(R2Store):
        def put(self, key, body, *, immutable=False):
            if key.startswith('catalog-generations/') or key == 'indexes/catalog.json':
                save('source/'+key, body)
            return super().put(key, body, immutable=immutable)
        def put_catalog_manifest(self, data, *, expected_version):
            manifest = json.loads(data)
            coverage = verify_coverage(source, manifest, expected)
            validate_document_indexes(source/manifest['files']['filenames']['key'],
                                      source/manifest['files']['documents']['key'])
            report('coverage.json', coverage)
            return super().put_catalog_manifest(data, expected_version=expected_version)
    try:
        guard()
        build = destination/'build'; build.mkdir(); (build/'indexes').mkdir()
        working = WorkingCatalog(build/'working.sqlite')
        try:
            with ProgressLog(destination/'catalog-progress.json'):
                catalog = rebuild_retained_catalog(Store(proxy,bucket), working=working, root=build)
        finally: working.close()
        report('catalog-result.json', catalog)
        mapping = publish_mappings(proxy, bucket=bucket,
            baseline=json.loads(args.baseline.read_text()), prepared=json.loads((batch/'accepted.json').read_text()),
            validate=accepted_rows, guard=guard, save_payload=save, journal=journal)
        report('mapping-result.json', mapping)
        builder = load(runtime/'apps/site/scripts/publish-filename-viewer.py', 'recovery_viewer_builder')
        builder.publish(source, destination/'prepared')
        guard()
        publisher = load(runtime/'apps/site/scripts/publish-viewer-r2.py', 'recovery_viewer_publisher')
        publication = publisher.run(proxy, prepared=destination/'prepared')
        if publication['status'] != 'published': raise ValueError('Viewer was not published')
        guard()
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
    parser.add_argument('--config', type=Path, default=ROOT/'.cache/r2-admin/rclone.conf')
    parser.add_argument('--execute', action='store_true')
    print(json.dumps(run(parser.parse_args()), indent=2))
