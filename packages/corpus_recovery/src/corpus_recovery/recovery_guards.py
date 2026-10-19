"""Bound expensive recovery checks by phase; keep shared commits fresh.

An immutable upload may reuse recent cloud clearance. A mutable object or shared
pointer must call shared_commit immediately before its conditional write.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time
from typing import Callable, Mapping

ACTIVE_STATUSES = ('queued', 'in_progress', 'requested', 'waiting', 'pending')


def active_cloud_writers(*, run=subprocess.check_output, max_pages=10):
    """Observe capture runs only; this is not an exclusion lease.

    Other publication writers are fenced by their own locks and per-object
    conditions. A successful inventory cannot exclude a writer starting later.
    """
    active = []
    for status in ACTIVE_STATUSES:
        for page in range(1, max_pages + 1):
            route = ('repos/civictechdc/congressional-tech/actions/workflows/'
                     f'capture-raw-sources.yml/runs?status={status}&per_page=100&page={page}')
            result = json.loads(run(['gh', 'api', route], text=True, timeout=30))
            if not isinstance(result, dict):
                raise RuntimeError('Cloud writer status malformed')
            rows = result.get('workflow_runs')
            if not isinstance(rows, list) or type(result.get('total_count')) is not int or result['total_count'] < 0:
                raise RuntimeError('Cloud writer status malformed')
            for row in rows:
                if (not isinstance(row, dict) or not isinstance(row.get('status'), str)
                        or type(row.get('id')) is not int or not isinstance(row.get('event'), str)):
                    raise RuntimeError('Cloud writer row malformed')
                if row['status'] == 'completed':
                    continue
                if row['status'] not in ACTIVE_STATUSES:
                    raise RuntimeError('Cloud writer status unknown')
                if row['event'] != 'push':
                    active.append(row['id'])
            if len(rows) < 100 and page * 100 >= result['total_count']:
                break
            if page == max_pages:
                raise RuntimeError('Cloud writer inventory incomplete')
    if active:
        raise RuntimeError(f'Cloud capture writer active: {sorted(set(active))}')


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _identity(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class RecoveryGuard:
    """One run's checks; never persist or reuse clearance in another process."""

    def __init__(self, *, pins: Mapping, local_check: Callable,
                 cloud_check: Callable, protected_check: Callable,
                 clock=time.monotonic, max_cloud_age=30.0):
        if not 0 <= max_cloud_age <= 30:
            raise ValueError('Cloud clearance lifetime must be between 0 and 30 seconds')
        self.pins = {Path(path): value for path, value in pins.items()}
        self.local_check, self.cloud_check = local_check, cloud_check
        self.protected_check, self.clock = protected_check, clock
        self.max_cloud_age = max_cloud_age
        self._identities = {}
        self._cloud_at = None
        self._lock = threading.RLock()
        self.counts = dict(local=0, hashed_files=0, cloud=0, protected=0)

    def _local(self):
        self.local_check()
        self.counts['local'] += 1

    def _pins(self, *, full):
        for path, expected in self.pins.items():
            before = _identity(path)
            if full or self._identities.get(path) != before:
                actual = _digest(path)
                self.counts['hashed_files'] += 1
                if actual != expected or _identity(path) != before:
                    raise RuntimeError(f'Pinned input changed: {path}')
                self._identities[path] = before

    def _cloud(self, *, fresh):
        now = self.clock()
        if fresh or self._cloud_at is None or now - self._cloud_at >= self.max_cloud_age:
            # A failed refresh must never leave a usable previous success.
            self._cloud_at = None
            self.counts['cloud'] += 1
            self.cloud_check()
            if self.clock() - now > 30:
                raise RuntimeError('Cloud writer check exceeded freshness window')
            self._cloud_at = now

    def check(self):
        """For immutable content writes only; content remains unselected."""
        with self._lock:
            self._local()
            self._pins(full=False)
            self._cloud(fresh=False)

    __call__ = check

    def boundary(self):
        """Check exact local custody and fresh protected versions at a phase seam.

        A new guard hashes every pin. The same process reuses only unchanged
        device/inode/size/mtime/ctime identities, including across phase seams.
        """
        with self._lock:
            self._local()
            self._pins(full=False)
            self._cloud(fresh=True)
            self.protected_check()
            self.counts['protected'] += 1
            self._local()
            self._pins(full=False)
            if self.clock() - self._cloud_at > 30:
                self._cloud_at = None
                raise RuntimeError('Shared commit checks exceeded freshness window')

    shared_commit = boundary
