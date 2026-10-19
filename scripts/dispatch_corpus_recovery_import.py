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
from corpus_recovery.import_corpus_recovery_batch import import_batch
from corpus_recovery.publication_import_evidence import compare_loaded_digest, compare_source_preparation
from corpus_recovery.recovery_guards import RecoveryGuard, active_cloud_writers
from congress_api.retention.raw_archive import CAPTURES_KEY, STATE_KEY, decode_table
from congress_api.retention.r2 import R2Store


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cloud_clear():
    return active_cloud_writers(run=subprocess.check_output)


def verify_batch(batch, readiness_path=None):
    manifest_bytes = (batch / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    readiness = json.loads((readiness_path or batch / 'import-readiness.json').read_text())
    if not readiness.get('ready', True):
        raise ValueError('Body reconciliation is not ready')
    expected = dict(manifest['files'])
    for name, value in readiness['files'].items():
        if name in expected and expected[name] != value:
            raise ValueError('Conflicting batch hashes')
        expected[name] = value
    loaded = {'manifest.json': manifest_bytes}
    for name, value in expected.items():
        if Path(name).name != name:
            raise ValueError(f'Batch changed: {name}')
        data = loaded.get(name)
        if data is None:
            data = (batch / name).read_bytes()
            loaded[name] = data
        compare_loaded_digest(data, value, lambda name=name: ValueError(f'Batch changed: {name}'))
    source_bytes = loaded.get('source-record-preparation.json')
    if source_bytes is None:
        source_bytes = (batch / 'source-record-preparation.json').read_bytes()
    compare_source_preparation(
        json.loads(source_bytes), hashlib.sha256(manifest_bytes).hexdigest(),
        lambda: ValueError('Incomplete or mismatched source preparation'))
    return expected


def run(args):
    batch = args.batch.resolve()
    readiness_path = (getattr(args, 'readiness', None) or batch / 'import-readiness.json').resolve()
    expected = verify_batch(batch, readiness_path)
    readiness = json.loads(readiness_path.read_text())
    readback_path = readiness_path.with_name('remote-body-readback.json')
    body_readback = None
    if readiness.get('remote_body_readback_sha256'):
        if digest(readback_path) != readiness['remote_body_readback_sha256']:
            raise ValueError('Body reconciliation evidence changed')
        body_readback = json.loads(readback_path.read_text())
        if body_readback['batch_manifest_sha256'] != digest(batch / 'manifest.json'):
            raise ValueError('Body reconciliation belongs to another batch')
    cloud_clear()
    if not args.execute:
        return dict(preflight=True, inputs_verified=True, cloud_clear=True, writes=False)
    control_root = (getattr(args, 'control_root', None) or ROOT).resolve()
    lock_path = control_root / '.cache/local-recovery.lock'
    lock = lock_path.open('a')
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
                 'assemble_corpus_recovery_import.py', 'reconcile_corpus_recovery_bodies.py',
                 'recovery_guards.py']:
        path = ROOT / 'scripts' / name
        code[path] = digest(path)
    import corpus_recovery.import_corpus_recovery_batch as import_batch_module
    import corpus_recovery.assemble_corpus_recovery_import as assemble_module
    import corpus_recovery.reconcile_corpus_recovery_bodies as reconcile_module
    import corpus_recovery.recovery_guards as guards_module
    import corpus_recovery.publication_import_evidence as evidence_module
    import viewer_publication.lost_acknowledgment as acknowledgment_module
    for executing in (import_batch_module, assemble_module, reconcile_module, guards_module,
                      evidence_module, acknowledgment_module):
        path = Path(executing.__file__).resolve()
        code[path] = digest(path)
    inputs = {batch / name: value for name, value in expected.items()}
    inputs[readiness_path] = digest(readiness_path)
    if body_readback is not None:
        inputs[readback_path] = readiness['remote_body_readback_sha256']
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
        if any(baseline.get(key) != value for key, value in readiness.get('expected_remote_versions', {}).items()):
            raise RuntimeError('Reconciliation baseline changed; reconcile again')
        journal('baseline', baseline)

        def local_check():
            if os.getppid() != parent or shutil.disk_usage(destination).free < 12 * 1024**3:
                raise RuntimeError('Parent or disk reserve changed')
            held = os.fstat(lock.fileno())
            named = lock_path.stat()
            if (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino):
                raise RuntimeError('Recovery lock file was replaced')

        def protected_check():
            for key, version in baseline.items():
                expected_version = store.index_etags.get(key, version)
                if client.head_object(Bucket=store.bucket, Key=key)['ETag'] != expected_version:
                    raise RuntimeError(f'Protected input changed: {key}')

        guard = RecoveryGuard(pins=code | inputs, local_check=local_check,
                              cloud_check=cloud_clear, protected_check=protected_check)
        guard.boundary()
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
            guard=guard.check, commit_guard=guard.shared_commit, body_readback=body_readback,
            journal=journal, save_payload=save_payload)
        guard.boundary()
        journal('guard_counts', guard.counts)
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
    parser.add_argument('--readiness', type=Path, help='Sealed readiness from the maintained reconciliation command.')
    parser.add_argument('--control-root', type=Path, default=ROOT, help='Shared checkout owning the recovery lock across runtimes.')
    parser.add_argument('--config', type=Path, default=ROOT / '.cache/r2-admin/rclone.conf')
    parser.add_argument('--connect-timeout', type=int, choices=range(15, 181), default=15,
                        help='Socket connection/write timeout for retained body uploads (seconds).')
    parser.add_argument('--execute', action='store_true')
    print(json.dumps(run(parser.parse_args()), indent=2))
