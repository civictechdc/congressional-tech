#!/usr/bin/env python3
"""Publish an accepted preparation in this local directory, with explicit custody."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path

from viewer_publication import attempt, publish_viewer_r2 as publisher
from viewer_publication.continuation import MAX_STATE_BYTES, bounded_json
from viewer_publication.publication_cli import make_client, save_report

RECEIPT = 'local-publication-receipt.json'
KIND = 'local_preparation'


def read_receipt(path):
    if path.is_symlink():
        raise ValueError('Local publication receipt cannot be a symbolic link')
    with path.open('rb') as stream:
        raw = stream.read(16385)
    if len(raw) > 16384:
        raise ValueError('Local publication receipt exceeds 16 KiB')
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get('kind') != KIND:
        raise ValueError('Invalid local preparation receipt')
    return value, raw


def publish_local(client, root, *, public_url=publisher.PUBLIC_URL, resume=False, probe=None):
    """Use the maintained inventory, conditional publisher and remote journal."""
    root = Path(root).resolve(strict=True)
    receipt_path = root / RECEIPT
    with (root / '.local-publication.lock').open('ab') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Local preparation is already being published') from error
        prior = read_receipt(receipt_path)[0] if resume else None
        if not resume and receipt_path.exists():
            raise ValueError('Local receipt already exists; use explicit --resume')

        def verify_local(artifact, prepared):
            if artifact != {'kind': KIND}:
                raise ValueError('Local preparation custody kind differs')
            # This callback runs only after the core verifies the complete output.
            # Bind the original bytes too, rather than a JSON re-encoding.
            with (root / 'preparation.json').open('rb') as stream:
                raw = stream.read(MAX_STATE_BYTES + 1)
            if len(raw) > MAX_STATE_BYTES or hashlib.sha256(raw).hexdigest() != prepared['preparation_sha256']:
                raise ValueError('Local preparation receipt bytes changed')
            preparation = json.loads(raw)
            producer = preparation.get('artifact_producer', preparation['binding'])
            info = root.stat()
            custody = dict(version=1, kind=KIND, directory=str(root),
                directory_identity=dict(device=info.st_dev, inode=info.st_ino),
                preparation_sha256=prepared['preparation_sha256'], attempt=prepared['attempt'],
                name=prepared['artifact_name'], run_id=producer['run_id'], run_attempt=producer['run_attempt'],
                provenance_revision=preparation['binding']['provenance_revision'],
                adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
            encoded = (json.dumps(custody, sort_keys=True, separators=(',', ':')) + '\n').encode()
            if resume:
                if read_receipt(receipt_path)[1] != encoded:
                    raise ValueError('Local preparation custody changed')
            else:
                state = bounded_json(root / 'continuation.json')
                if state['writes'] or state['versions']:
                    raise ValueError('Existing publication state requires its original local receipt and --resume')
                # Exclusive creation prevents silently replacing local authority.
                # A torn receipt refuses resume; it is never regenerated.
                with receipt_path.open('xb') as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                directory = os.open(root, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            return dict(custody, local_receipt_sha256=hashlib.sha256(encoded).hexdigest())

        return attempt.publish(publisher, client, root, artifact={'kind': KIND},
            public_url=public_url, resume=resume, attempt=prior.get('attempt') if prior else None,
            verify_artifact=verify_local, **({'probe': probe} if probe is not None else {}))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--public-url', default=publisher.PUBLIC_URL)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = publish_local(make_client(), args.directory, public_url=args.public_url, resume=args.resume)
    except BaseException as error:
        try:
            save_report(args.report, dict(status='failed', error_type=type(error).__name__, error=str(error)))
        except BaseException as diagnostic:
            error.add_note('Local publication report failed: ' + type(diagnostic).__name__)
        raise
    save_report(args.report, result)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] in ('published', 'recovery_updated', 'unchanged') else 1


if __name__ == '__main__':
    raise SystemExit(main())
