"""One-shot guarded raw import. Default mode checks inputs and cloud ownership only."""
import argparse
import configparser
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'packages/congress_api/src'))
from import_corpus_recovery_batch import import_batch
from congress_api.retention.raw_archive import CAPTURES_KEY, STATE_KEY, decode_table
from congress_api.retention.r2 import R2Store


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cloud_clear():
    pages = json.loads(subprocess.check_output([
        'gh', 'api', '--paginate', '--slurp',
        'repos/civictechdc/congressional-tech/actions/workflows/capture-raw-sources.yml/runs?per_page=100',
    ], text=True, timeout=60))
    active = [r['id'] for page in pages for r in page['workflow_runs']
              if r['event'] != 'push' and r['status'] != 'completed']
    if active:
        raise RuntimeError(f'Cloud capture writer active: {active}')


def verify_batch(batch):
    manifest = json.loads((batch / 'manifest.json').read_text())
    readiness = json.loads((batch / 'import-readiness.json').read_text())
    expected = dict(manifest['files'])
    for name, value in readiness['files'].items():
        if name in expected and expected[name] != value:
            raise ValueError('Conflicting batch hashes')
        expected[name] = value
    for name, value in expected.items():
        if Path(name).name != name or digest(batch / name) != value:
            raise ValueError(f'Batch changed: {name}')
    source = json.loads((batch / 'source-record-preparation.json').read_text())
    if source['unresolved'] or source['batch_manifest_sha256'] != digest(batch / 'manifest.json'):
        raise ValueError('Incomplete or mismatched source preparation')
    return expected


def run(args):
    batch = args.batch.resolve()
    expected = verify_batch(batch)
    cloud_clear()
    if not args.execute:
        return dict(preflight=True, inputs_verified=True, cloud_clear=True, writes=False)
    lock = (ROOT / '.cache/local-recovery.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    cloud_clear()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    parent = os.getppid()

    def save_payload(key, payload):
        path = destination / 'payloads' / key
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

    def journal(event, value):
        with (destination / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),
                                         event=event, value=value)) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    code = {p.resolve(): digest(p) for p in (ROOT / 'packages/congress_api/src').rglob('*.py')}
    for name in ['dispatch_corpus_recovery_import.py', 'import_corpus_recovery_batch.py',
                 'assemble_corpus_recovery_import.py']:
        path = ROOT / 'scripts' / name
        code[path] = digest(path)
    inputs = {batch / name: value for name, value in expected.items()}
    inputs[batch / 'import-readiness.json'] = digest(batch / 'import-readiness.json')
    journal('pins', {str(k): v for k, v in (code | inputs).items()})
    try:
        import boto3
        from botocore.config import Config
        config = configparser.ConfigParser()
        config.read(args.config)
        account = config['congressionalraw']
        client = boto3.client('s3', endpoint_url=account['endpoint'], region_name='auto',
            aws_access_key_id=account['access_key_id'], aws_secret_access_key=account['secret_access_key'],
            config=Config(connect_timeout=args.connect_timeout, read_timeout=180, retries={'total_max_attempts': 1},
                          request_checksum_calculation='when_required', response_checksum_validation='when_required'))
        store = R2Store(client, 'congressional-tech-raw')
        baseline = {}
        for key in [CAPTURES_KEY, STATE_KEY, 'indexes/catalog.json',
                    'viewer-publications/recoveries/accepted.json']:
            response = client.get_object(Bucket=store.bucket, Key=key)
            with response['Body'] as stream:
                data = stream.read()
            if len(data) != response['ContentLength']:
                raise ValueError(f'Incomplete baseline: {key}')
            save_payload('baseline/' + key, data)
            baseline[key] = response['ETag']
            if key.startswith('indexes/'):
                store.index_etags[key] = response['ETag']
        journal('baseline', baseline)

        def guard():
            if os.getppid() != parent or shutil.disk_usage(destination).free < 12 * 1024**3:
                raise RuntimeError('Parent or disk reserve changed')
            held = os.fstat(lock.fileno())
            named = (ROOT / '.cache/local-recovery.lock').stat()
            if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
                raise RuntimeError('Recovery lock file was replaced')
            for path, value in (code | inputs).items():
                if digest(path) != value:
                    raise ValueError(f'Pinned input changed: {path}')
            cloud_clear()
            for key, version in baseline.items():
                expected_version = store.index_etags.get(key, version)
                if client.head_object(Bucket=store.bucket, Key=key)['ETag'] != expected_version:
                    raise RuntimeError(f'Protected input changed: {key}')

        guard()
        inventory = json.loads((batch / 'bodies.json').read_text())
        prepared = json.loads((batch / 'prepared-source-records.json').read_text())
        prepared += json.loads((batch / 'zip-receipts.json').read_text())
        run_id = 'corpus-recovery-' + uuid.uuid4().hex
        result = import_batch(store, prepared=prepared,
            body_paths={key: info['path'] for key, info in inventory.items()},
            captures=decode_table((destination / 'payloads/baseline' / CAPTURES_KEY).read_bytes()),
            state=decode_table((destination / 'payloads/baseline' / STATE_KEY).read_bytes()),
            source_file='ci/' + run_id,
            receipt_prefix='receipts/documents/' + datetime.now(timezone.utc).date().isoformat() + '/' + run_id,
            guard=guard, journal=journal, save_payload=save_payload)
        save_payload('import-complete.json', json.dumps(result, indent=2).encode())
        return result
    except BaseException as error:
        journal('failed_requires_reconciliation', dict(error_type=type(error).__name__, error=str(error)))
        raise
    finally:
        lock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT / '.cache/r2-admin/rclone.conf')
    parser.add_argument('--connect-timeout', type=int, choices=range(15, 181), default=15,
                        help='Socket connection/write timeout for retained body uploads (seconds).')
    parser.add_argument('--execute', action='store_true')
    print(json.dumps(run(parser.parse_args()), indent=2))
