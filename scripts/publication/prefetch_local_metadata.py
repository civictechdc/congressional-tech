#!/usr/bin/env python3
"""Warm the maintained metadata cache from hints in a stopped renderer database.

Hints authorize no publication or checkpoint reuse. A fresh builder must read
its live selectors and validate cached bytes against their current references.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
import hashlib
from itertools import islice
import json
from pathlib import Path
import re
import sqlite3
import time

from congress_api.retention.r2 import R2Store
from congress_shared.custody import write_atomic_bytes
from viewer_publication.constants import BUCKET
from viewer_publication.publication_cli import save_report
from prepare_local_release import make_client, RETRIES

ROUTES = 'catalog-component-selection-v2'
PROOFS = 'catalog-component-pages-v1'
MAX_BYTES = 1 << 20  # Same limit as maintained MetadataObjects for these namespaces.
KEY = re.compile(r'indexes/native-manifests/(' + ROUTES + '|' + PROOFS + r')/([a-f0-9]{64})\.json\Z')


@dataclass(frozen=True)
class Hint:
    key: str
    sha256: str
    size: int | None = None

    def __post_init__(self):
        match = KEY.fullmatch(self.key) if isinstance(self.key, str) else None
        if not match or match[2] != self.sha256:
            raise ValueError('Metadata hint is outside the immutable allowlist')
        if self.size is not None and (type(self.size) is not int or not 0 < self.size <= MAX_BYTES):
            raise ValueError('Metadata hint exceeds its byte bound')


def read_hints(path):
    """Read a stopped database normally, without bypassing SQLite locks."""
    connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        connection.execute('PRAGMA query_only=ON')
        hints = {}
        for raw, in connection.execute('SELECT body FROM plans'):
            digest = json.loads(raw)['native_sha256']
            hint = Hint(f'indexes/native-manifests/{ROUTES}/{digest}.json', digest)
            hints[hint.key] = hint
        for raw, in connection.execute('SELECT DISTINCT page FROM components'):
            value = json.loads(raw)
            hint = Hint(value['key'], value['sha256'], value['bytes'])
            old = hints.get(hint.key)
            if old is not None and old != hint:
                raise ValueError('Conflicting metadata hints')
            hints[hint.key] = hint
        return list(hints.values())
    finally:
        connection.close()


def checked(raw, hint):
    if (raw is None or not 0 < len(raw) <= MAX_BYTES
            or hint.size is not None and len(raw) != hint.size
            or hashlib.sha256(raw).hexdigest() != hint.sha256):
        raise ValueError('Metadata hint content identity mismatch: ' + hint.key)
    return raw


def prefetch(client, hints, cache_dir, *, workers=16, progress=None):
    if type(workers) is not int or not 1 <= workers <= 32:
        raise ValueError('Metadata prefetch workers must be between 1 and 32')
    cache_dir = Path(cache_dir)
    # The fetching store has no in-memory/disk retention. This command only
    # populates the existing R2Store/MetadataObjects disk format after hashing;
    # it adds no SDK cache or alternate metadata reader to preparation.
    store = R2Store(client, BUCKET)
    def fetch(hint):
        match = KEY.fullmatch(hint.key)
        path = cache_dir / 'r2-native-manifests' / match[1] / (hint.sha256 + '.json')
        if path.is_file():
            try:
                with path.open('rb') as stream:
                    raw = checked(stream.read(MAX_BYTES + 1), hint)
                return 'cached', len(raw)
            except (OSError, ValueError):
                pass  # Refetch corrupt cache bytes; never authorize their use.
        raw = checked(store.read(hint.key), hint)
        write_atomic_bytes(path, raw, temp_mode='unique')
        return 'downloaded', len(raw)
    result = dict(status='prefetched', total=len(hints), completed=0, cached=0,
                  downloaded=0, bytes=0, failures=0, workers=workers)
    started, notified = time.monotonic(), time.monotonic()
    notified_count = 0
    iterator = iter(hints)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(fetch, hint) for hint in islice(iterator, workers)}
        try:
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    kind, size = future.result()
                    result[kind] += 1
                    result['bytes'] += size
                    result['completed'] += 1
                now = time.monotonic()
                if progress and (now - notified >= 15 or result['completed'] - notified_count >= 256
                                 or result['completed'] == len(hints)):
                    progress(dict(result, status='prefetching', elapsed_seconds=now - started))
                    notified, notified_count = now, result['completed']
                pending.update(pool.submit(fetch, hint) for hint in islice(iterator, workers - len(pending)))
        except BaseException as error:
            result['failures'] += 1
            if progress:
                progress(dict(result, status='failed', error_type=type(error).__name__,
                    elapsed_seconds=time.monotonic() - started))
            for future in pending:
                future.cancel()
            raise
    return dict(result, elapsed_seconds=time.monotonic() - started)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stages', type=Path, required=True, help='Stopped renderer stages.sqlite; read-only hints')
    parser.add_argument('--metadata-cache', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=(16, 32), default=16)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    operation = dict(version=1, kind='local_metadata_prefetch',
        adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), retries=dict(RETRIES),
        stages=str(args.stages.resolve()), metadata_cache=str(args.metadata_cache.resolve()))
    latest = dict(operation, status='started', completed=0, bytes=0, failures=0, elapsed_seconds=0)
    try:
        hints = read_hints(args.stages)
        latest.update(total=len(hints), workers=args.workers,
            proof_declared_bytes=sum(hint.size or 0 for hint in hints))
        save_report(args.report, latest)
        print(json.dumps(latest, sort_keys=True), flush=True)
        def progress(event):
            latest.update(event)
            save_report(args.report, latest)
            print(json.dumps(event, sort_keys=True), flush=True)
        result = dict(operation, **prefetch(make_client(max_pool_connections=args.workers), hints, args.metadata_cache, workers=args.workers,
            progress=progress))
        save_report(args.report, result)
    except BaseException as error:
        try:
            save_report(args.report, dict(latest, status='failed', error_type=type(error).__name__))
        except BaseException as diagnostic:
            error.add_note('Metadata prefetch report failed: ' + type(diagnostic).__name__)
        raise
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
