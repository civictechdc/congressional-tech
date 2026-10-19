"""Read-only reconciliation of a sealed recovery batch and retained body versions.

Prior evidence is reusable only when its caller-pinned file digest, exact desired
body identity, and a fresh remote ETag and size all agree. Unknown versions need
full byte verification. This command never writes to the object store.
"""
import argparse
from collections import Counter
import configparser
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
from corpus_recovery.publication_import_evidence import compare_loaded_digest, compare_source_preparation


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reusable_result(key, desired, prior):
    """Require explicit identities, never infer verification from a status alone."""
    sha = desired.get('sha256', '')
    return (isinstance(sha, str) and re.fullmatch('[0-9a-f]{64}', sha) is not None
            and key == f'bodies/sha256/{sha[:2]}/{sha}.gz'
            and prior.get('status') == 'verified_exact_body'
            and prior.get('sha256') == sha
            and type(prior.get('raw_bytes')) is int
            and prior['raw_bytes'] == desired.get('bytes')
            and type(prior.get('stored_bytes')) is int and prior['stored_bytes'] > 0
            and isinstance(prior.get('stored_sha256'), str)
            and re.fullmatch('[0-9a-f]{64}', prior['stored_sha256']) is not None
            and isinstance(prior.get('etag'), str) and bool(prior['etag']))


def head_body(store, key):
    from botocore.exceptions import ClientError
    try:
        return store.client.head_object(Bucket=store.bucket, Key=key)
    except ClientError as error:
        if error.response['Error']['Code'] in {'NoSuchKey', '404', 'NotFound'}:
            return None
        raise


def reconcile(store, inventory, *, prior=None):
    results = {}
    for key, info in inventory.items():
        sha = info['sha256']
        if key != f'bodies/sha256/{sha[:2]}/{sha}.gz' or type(info['bytes']) is not int or info['bytes'] < 0:
            raise ValueError(f'Invalid desired body identity: {key}')
        old = (prior or {}).get('results', {}).get(key, {})
        try:
            head = head_body(store, key)
            if head is None:
                results[key] = dict(status='absent', upload_required=True, sha256=sha, raw_bytes=info['bytes'])
                continue
            if reusable_result(key, info, old) and (head['ETag'], head['ContentLength']) == (old['etag'], old['stored_bytes']):
                results[key] = dict(old, verification='prior_full_bytes_plus_fresh_version_and_size')
                continue
            # Bind the bytes to their GET response, not to the earlier HEAD.
            response = store.client.get_object(Bucket=store.bucket, Key=key)
            with response['Body'] as stream:
                stored = stream.read()
            if len(stored) != response['ContentLength']:
                raise ValueError('Incomplete remote body')
            with gzip.GzipFile(fileobj=io.BytesIO(stored)) as stream:
                raw = stream.read(info['bytes'] + 1)
            exact = len(raw) == info['bytes'] and hashlib.sha256(raw).hexdigest() == sha
            results[key] = dict(status='verified_exact_body' if exact else 'conflict',
                                sha256=sha, raw_bytes=len(raw), etag=response['ETag'],
                                stored_sha256=hashlib.sha256(stored).hexdigest(), stored_bytes=len(stored),
                                verification='full_body_sha256', upload_required=False if exact else None)
        except Exception as error:
            results[key] = dict(status='unresolved', error_type=type(error).__name__, error=str(error))
    return dict(read_only=True, bodies=len(results), counts=dict(Counter(r['status'] for r in results.values())),
                results=results)


def sealed_inputs(batch):
    def changed(name):
        return ValueError(f'Batch changed: {name}')

    manifest_bytes = (batch / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_bytes)
    files = dict(manifest['files'])
    files['manifest.json'] = hashlib.sha256(manifest_bytes).hexdigest()
    loaded = {'manifest.json': manifest_bytes}
    for name in ('prepared-source-records.json', 'source-record-preparation.json'):
        data = (batch / name).read_bytes()
        loaded[name] = data
        if name in files:
            compare_loaded_digest(data, files[name], lambda name=name: changed(name))
        else:
            files[name] = hashlib.sha256(data).hexdigest()
    for name, expected in files.items():
        if Path(name).name != name:
            raise changed(name)
        data = loaded.get(name)
        if data is None:
            data = (batch / name).read_bytes()
            loaded[name] = data
        compare_loaded_digest(data, expected, lambda name=name: changed(name))
    source = json.loads(loaded['source-record-preparation.json'])
    compare_source_preparation(
        source, files['manifest.json'],
        lambda: ValueError('Incomplete or mismatched source preparation'))
    prepared = json.loads(loaded['prepared-source-records.json'])
    prepared += json.loads(loaded['zip-receipts.json'] if 'zip-receipts.json' in loaded
                           else (batch / 'zip-receipts.json').read_bytes())
    inventory = json.loads(loaded['bodies.json'] if 'bodies.json' in loaded
                           else (batch / 'bodies.json').read_bytes())
    captures = [cap for item in prepared for cap in item['captures']]
    if {cap['body_key'] for cap in captures} != set(inventory):
        raise ValueError('Capture/body inventory coverage differs')
    for cap in captures:
        if any(cap[field] != inventory[cap['body_key']][field] for field in ('sha256', 'bytes')):
            raise ValueError('Capture/body identity differs')
    return files, inventory, dict(receipt_records=len(prepared), capture_rows=len(captures), distinct_bodies=len(inventory))


def run(args):
    batch = args.batch.resolve()
    files, inventory, counts = sealed_inputs(batch)
    prior = None
    if args.prior:
        if not args.prior_sha256 or digest(args.prior) != args.prior_sha256:
            raise ValueError('Prior evidence digest mismatch')
        prior = json.loads(args.prior.read_text())
    import boto3
    from botocore.config import Config
    from congress_api.retention.r2 import R2Store
    config = configparser.ConfigParser()
    config.read(args.config)
    account = config['congressionalraw']
    client = boto3.client('s3', endpoint_url=account['endpoint'], region_name='auto',
                          aws_access_key_id=account['access_key_id'], aws_secret_access_key=account['secret_access_key'],
                          config=Config(connect_timeout=15, read_timeout=180, retries={'total_max_attempts': 1}))
    store = R2Store(client, 'congressional-tech-raw')
    report = reconcile(store, inventory, prior=prior)
    report.update(at=datetime.now(timezone.utc).isoformat(), batch_manifest_sha256=files['manifest.json'], files=files)
    if args.prior:
        report.update(prior_evidence_sha256=args.prior_sha256)
    # State the versions expected at the next guarded dispatch, without admitting writes.
    versions = {key: client.head_object(Bucket=store.bucket, Key=key)['ETag'] for key in
                ('indexes/captures.parquet', 'indexes/download-state.parquet', 'indexes/catalog.json',
                 'viewer-publications/recoveries/accepted.json')}
    args.destination.mkdir(parents=True, exist_ok=False)
    report_path = args.destination / 'remote-body-readback.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    readiness = dict(at=report['at'], files=files, **counts, remote_existing=report['counts'].get('verified_exact_body', 0),
                     remote_absent=report['counts'].get('absent', 0), expected_remote_versions=versions,
                     remote_body_readback_sha256=digest(report_path), batch=str(batch),
                     ready=all(r['status'] in {'verified_exact_body', 'absent'} for r in report['results'].values()),
                     writes_authorized=False)
    (args.destination / 'import-readiness.json').write_text(json.dumps(readiness, indent=2) + '\n')
    return readiness


def main(argv=None, *, root):
    """Run the reconciliation command against the checkout that owns the lock config."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--prior', type=Path)
    parser.add_argument('--prior-sha256')
    parser.add_argument('--config', type=Path, default=Path(root) / '.cache/r2-admin/rclone.conf')
    print(json.dumps(run(parser.parse_args(argv)), indent=2))
