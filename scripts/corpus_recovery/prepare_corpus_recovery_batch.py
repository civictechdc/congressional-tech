"""Seal a local recovery batch for later guarded import; never write remotely."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def prepare(source, deferred_path, destination):
    source = Path(source)
    destination = Path(destination)
    inputs = {}
    def read(path):
        path = Path(path)
        raw = path.read_bytes()
        inputs[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    recovered = read(source / 'recovered-files.json')
    receipts = read(source / 'prepared-zip-receipts.json')
    members = read(source / 'zip-member-reconciliation.json')
    deferred_rows = read(deferred_path)
    deferred = {r['url'] for r in deferred_rows}
    deferred_hashes = {r['sha256'] for r in deferred_rows if r.get('sha256')}
    deferred_keys = {r['body_key'] for r in deferred_rows if r.get('body_key')}
    accepted = read(source / 'prepared-accepted.json')
    bodies = {}
    def body(key, path, expected_size=None):
        path = Path(path)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if key != f'bodies/sha256/{digest[:2]}/{digest}.gz':
            raise ValueError(f'Body identity mismatch: {path}')
        if digest in deferred_hashes or key in deferred_keys:
            raise ValueError(f'Deferred body cannot enter recovery batch: {path}')
        size = path.stat().st_size
        if expected_size is not None and size != expected_size:
            raise ValueError(f'Body size mismatch: {path}')
        bodies.setdefault(key, dict(path=str(path.resolve()), sha256=digest, bytes=size))
    urls = set()
    for row in recovered:
        if not row.get('validated') or row['original_url'] in deferred:
            raise ValueError('Unvalidated or deferred recovery')
        if row['original_url'] in urls:
            raise ValueError('Duplicate recovered URL')
        urls.add(row['original_url'])
        body(row['body_key'], row['body_path'], row['bytes'])
    validated_members = {row['body_key']: row for row in members if row.get('validated')}
    member_keys = set()
    for receipt in receipts:
        if not receipt.get('preserve_download_state') or receipt['original_url'] in deferred:
            raise ValueError('ZIP state preservation or exclusion check failed')
        for capture in receipt['captures']:
            key = capture['body_key']
            body(key, receipt['local_bodies'][key], capture['bytes'])
            if capture['pointer'][0] == 'archive_members':
                if key not in validated_members or not capture.get('original_path'):
                    raise ValueError('ZIP member validation or parent context missing')
                member_keys.add(key)
    if member_keys != set(validated_members):
        raise ValueError('ZIP member coverage mismatch')
    accepted_pairs = {(r['original_url'], r['body_key']) for r in accepted['recoveries']}
    if any((r['original_url'], r['body_key']) not in accepted_pairs for r in recovered):
        raise ValueError('Recovered URL missing from accepted mappings')
    # Existing directories are immutable snapshots, never implicit resumes.
    destination.mkdir(parents=True, exist_ok=False)
    for name, value in [('recoveries.json', recovered), ('zip-receipts.json', receipts),
                        ('accepted.json', accepted), ('bodies.json', bodies)]:
        (destination / name).write_text(json.dumps(value, indent=2) + '\n')
    manifest = dict(created_at=datetime.now(timezone.utc).isoformat(),
                    status='validated_local_batch_not_imported_or_published',
                    recovered_urls=len(urls), zip_parents=len(receipts),
                    zip_distinct_members=len(member_keys), distinct_bodies=len(bodies),
                    deferred_urls_excluded=len(deferred), input_hashes=inputs,
                    files={f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                           for f in sorted(destination.glob('*.json'))},
                    publication_requires=['fresh_cloud_clear', 'local_recovery_lock',
                                          'fresh_input_versions_and_rebase',
                                          'conditional_publication', 'remote_readback'])
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--deferred', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.deferred, args.destination), indent=2))
