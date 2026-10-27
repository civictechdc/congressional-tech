#!/usr/bin/env python3
"""Publish an accepted preparation in this local directory, with explicit custody."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from viewer_publication import attempt, publish_viewer_r2 as publisher
from viewer_publication.continuation import MAX_STATE_BYTES, bounded_json
from viewer_publication.publication_cli import make_client, save_report
from viewer_publication.local import LocalContinuation
from viewer_publication.client import ContinuedPublicationClient

RECEIPT = 'local-publication-receipt.json'
KIND = 'local_preparation'
LOCAL_STATE = 'local-publication-state'
MAX_PRETRANSFER_WORKERS = 512
COMPATIBLE_ADAPTER_SHA256 = '447a6a7f2f88ceae0d0d3e139ea6d653122575aab23a7660e03a6bd704647f82'


def adapter_sha256():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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


def pretransfer_assets(client, plan, workers):
    """Transfer only accepted v6 content-addressed payloads; selection stays core-owned."""
    if plan.manifest.get('version') != 6:
        raise ValueError('Parallel pre-transfer requires a verified v6 plan')
    plan.require(plan.root, plan.manifest)

    def transfer(item):
        name, path = item
        match = re.fullmatch(r'releases/([a-f0-9]{32})/([a-f0-9]{32})/viewer-v2/([^/]+)', name)
        if not match or match[3] == 'manifest.json' or match[3].startswith('recovery'):
            return
        proof = plan.validation.file(path)
        if proof['sha256'] != match[1] + match[2]:
            raise ValueError('Pre-transfer asset address differs from verified bytes')
        content_type = ('application/vnd.apache.parquet' if name.endswith('.parquet') else
                        'application/json' if name.endswith('.json') else 'application/octet-stream')
        client.upload_verified_file(str(path), publisher.BUCKET, publisher.PREFIX + name,
            validation=proof, ExtraArgs=dict(ContentType=content_type,
                CacheControl='public, max-age=31536000, immutable', Metadata={'sha256': proof['sha256']}))

    pending, items, exhausted = set(), iter(plan.files.items()), False
    # The executor context drains running workers before any exception escapes
    # the full-operation local lock. Submitted work is bounded too.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        try:
            while True:
                while not exhausted and len(pending) < workers:
                    item = next(items, None)
                    if item is None:
                        exhausted = True
                        break
                    pending.add(pool.submit(transfer, item))
                if not pending:
                    return
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    future.result()
        except BaseException:
            for future in pending:
                future.cancel()
            raise


def publish_local(client, root, *, public_url=publisher.PUBLIC_URL, resume=False, probe=None, journal_mode='local', pretransfer_workers=0, resume_adapter_sha256=None):
    """Publish with a synced local event chain, or explicitly select remote journaling.

    Keep the complete preparation directory on persistent local storage for resume.
    The receipt binds the chosen journal authority; modes cannot be switched.
    """
    if type(pretransfer_workers) is not int or not 0 <= pretransfer_workers <= MAX_PRETRANSFER_WORKERS:
        raise ValueError('Pre-transfer workers must be between 0 and 512')
    if resume_adapter_sha256 is not None and (resume_adapter_sha256 != COMPATIBLE_ADAPTER_SHA256
            or not resume or journal_mode != 'local'):
        raise ValueError('Adapter compatibility requires explicit local resume of the exact supported predecessor')
    if pretransfer_workers:
        pool = getattr(getattr(getattr(client, 'meta', None), 'config', None), 'max_pool_connections', None)
        if journal_mode != 'local' or not isinstance(pool, int) or pool < pretransfer_workers:
            raise ValueError('Pre-transfer requires local journaling and a matching SDK connection pool')
    if journal_mode not in ('local', 'remote'):
        raise ValueError('Unsupported local publication journal mode')
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
            custody = dict(version=1, kind=KIND, journal_mode=journal_mode, directory=str(root),
                directory_identity=dict(device=info.st_dev, inode=info.st_ino),
                preparation_sha256=prepared['preparation_sha256'], attempt=prepared['attempt'],
                name=prepared['artifact_name'], run_id=producer['run_id'], run_attempt=producer['run_attempt'],
                provenance_revision=preparation['binding']['provenance_revision'],
                adapter_sha256=resume_adapter_sha256 or adapter_sha256())
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
                sync_directory(root)
            return dict(custody, local_receipt_sha256=hashlib.sha256(encoded).hexdigest())

        if journal_mode == 'remote':
            return attempt.publish(publisher, client, root, artifact={'kind': KIND},
                public_url=public_url, resume=resume, attempt=prior.get('attempt') if prior else None,
                verify_artifact=verify_local, **({'probe': probe} if probe is not None else {}))

        verified = attempt.verify_prepared(publisher, root)
        receipt, manifest, prepared = verified
        if receipt['binding']['mode'] != 'full':
            raise ValueError('Local journaling requires full preparation; select --journal-mode remote for recovery-only output')
        custody = verify_local({'kind': KIND}, prepared)
        state = LocalContinuation(root / LOCAL_STATE, {'custody': custody}, resume=resume)
        # LocalContinuation syncs its journal and own directory. Persist the
        # new state directory's entry in the preparation parent before any PUT.
        sync_directory(root)
        binding = receipt['binding']
        versions = state.value['versions']
        protected = (('indexes/catalog.json', 'source'), (publisher.ACCEPTED_KEY, 'accepted'),
                     (publisher.PREFIX + 'manifest.json', 'viewer'))
        if not versions:
            versions.update({key: binding[name]['etag'] for key, name in protected})
            state.flush()
        if resume:
            # A pointer may have committed before its acknowledgment was synced.
            # Reconcile its exact bytes and version before checking selectors.
            state.reconcile(client, publisher.BUCKET)

        def check_inputs():
            for key, name in protected:
                current = attempt.record_input(publisher, client, key, optional=name != 'source')
                if current['etag'] != versions[key] or (name != 'viewer' and current['value'] != binding[name]['value']):
                    raise attempt.Superseded('Publication input changed: ' + key)

        class PublicationGuard:
            def check(self):
                return None  # Immutable uploads remain unselected until guarded commit.
            def shared_commit(self):
                check_inputs()

        try:
            check_inputs()
            if resume_adapter_sha256 is not None:
                state.record('local_adapter_compatibility_authorized', dict(
                    version=1, predecessor_adapter_sha256=resume_adapter_sha256,
                    current_adapter_sha256=adapter_sha256(),
                    original_local_receipt_sha256=custody['local_receipt_sha256'],
                    preparation_sha256=custody['preparation_sha256'],
                    attempt=custody['attempt'], pretransfer_workers=pretransfer_workers,
                    authorization='Explicit --resume-adapter-sha256 for bounded concurrency increase; original custody and journal binding retained'))
            guarded = ContinuedPublicationClient(client, continuation=state, guard=PublicationGuard(),
                journal=state.record, after_write=lambda *args: None)
            if pretransfer_workers:
                pretransfer_assets(guarded, verified.plan, pretransfer_workers)
            result = publisher.upload(guarded, root / 'publication', manifest,
                previous_etag=binding['viewer']['etag'], selected_etag=binding['source']['etag'],
                public_url=public_url, publication_plan=receipt['release_plan'], plan=verified.plan,
                **({'probe': probe} if probe is not None else {}))
            state.record('publication_completed', result)
            state.save('publication-result.json', publisher.encoded(result), replace=True)
            return dict(result, attempt=prepared['attempt'], preparation_reused=resume, journal_mode=journal_mode,
                pretransfer_workers=pretransfer_workers)
        except BaseException as error:
            try:
                state.record('publication_failed', {'error_type': type(error).__name__, 'error': str(error)})
            except BaseException as diagnostic:
                error.add_note('Local publication diagnostic failed: ' + type(diagnostic).__name__)
            if isinstance(error, attempt.Superseded):
                return dict(status='superseded', reason=str(error), attempt=prepared['attempt'], journal_mode=journal_mode)
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--public-url', default=publisher.PUBLIC_URL)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--journal-mode', choices=('local', 'remote'), default='local')
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--pretransfer-workers', type=int, choices=range(MAX_PRETRANSFER_WORKERS + 1), default=0,
        help='Opt-in v6 asset concurrency (0 disables; at most 512), with matching SDK pool')
    parser.add_argument('--resume-adapter-sha256', choices=(COMPATIBLE_ADAPTER_SHA256,),
        help='Explicitly resume the exact supported predecessor receipt/journal without rebinding custody')
    args = parser.parse_args(argv)
    try:
        if args.pretransfer_workers:
            from congress_shared.storage import connect_r2
            client = connect_r2(connect_timeout=15, read_timeout=180,
                retries={'total_max_attempts': 1}, max_pool_connections=args.pretransfer_workers)
        else:
            client = make_client()
        result = publish_local(client, args.directory, public_url=args.public_url, resume=args.resume,
            journal_mode=args.journal_mode, pretransfer_workers=args.pretransfer_workers,
            resume_adapter_sha256=args.resume_adapter_sha256)
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
