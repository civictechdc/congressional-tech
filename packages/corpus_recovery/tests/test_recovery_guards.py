import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

from corpus_recovery.guards import RecoveryGuard, active_cloud_writers


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'input'; self.path.write_bytes(b'sealed')
        self.local, self.cloud, self.protected = Mock(), Mock(), Mock()
        self.now = 0
        self.guard = RecoveryGuard(pins={self.path: hashlib.sha256(b'sealed').hexdigest()},
            local_check=self.local, cloud_check=self.cloud, protected_check=self.protected,
            clock=lambda: self.now)

    def test_many_immutable_writes_recheck_pins_and_share_only_cloud_clearance(self):
        self.guard.boundary()
        for _ in range(1000): self.guard.check()
        self.assertEqual(self.guard.counts, dict(local=1002, hashed_files=1002, cloud=1, protected=1))
        self.guard.shared_commit()
        self.assertEqual(self.guard.counts, dict(local=1004, hashed_files=1004, cloud=2, protected=2))

    def test_unknown_cloud_invalidates_allowance(self):
        self.guard.check(); self.now = 31
        self.cloud.side_effect = TimeoutError('unknown')
        for _ in range(2):
            with self.assertRaises(TimeoutError): self.guard.check()
        self.assertEqual(self.cloud.call_count, 3)
        self.cloud.side_effect = None
        self.guard.check(); self.assertEqual(self.cloud.call_count, 4)

    def test_slow_cloud_scan_cannot_mint_fresh_clearance(self):
        def slow():self.now += 31
        self.cloud.side_effect = slow
        with self.assertRaisesRegex(RuntimeError, 'freshness window'):self.guard.shared_commit()
        self.assertIsNone(self.guard._cloud_at)
        self.assertEqual(self.protected.call_count, 0)
    def test_slow_protected_check_refuses_before_commit(self):
        self.protected.side_effect = lambda: setattr(self, 'now', self.now + 31)
        with self.assertRaisesRegex(RuntimeError, 'freshness window'):self.guard.shared_commit()
        self.assertIsNone(self.guard._cloud_at)
    def test_local_ownership_rechecked_after_remote_checks(self):
        self.protected.side_effect = lambda: setattr(self.local, 'side_effect', RuntimeError('lock lost'))
        with self.assertRaisesRegex(RuntimeError, 'lock lost'):self.guard.shared_commit()
    def test_changes_fail_before_next_write(self):
        self.guard.boundary(); self.path.write_bytes(b'change')
        with self.assertRaisesRegex(RuntimeError, 'Pinned input changed'): self.guard.check()

    def test_shared_commit_checks_protected_version_fresh(self):
        self.guard.boundary()
        self.protected.side_effect = RuntimeError('Protected input changed')
        self.guard.check()
        with self.assertRaisesRegex(RuntimeError, 'Protected input changed'): self.guard.shared_commit()

    def test_lost_local_ownership_blocks_even_with_fresh_cloud(self):
        self.guard.check(); self.local.side_effect = RuntimeError('lock changed')
        with self.assertRaisesRegex(RuntimeError, 'lock changed'): self.guard.check()

    def test_active_inventory_paginates_only_active_results(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command[-1])
            rows = [dict(id=i, event='push', status='queued') for i in range(100)]
            if 'status=queued' in command[-1]:
                if 'page=2' in command[-1]:
                    rows = [dict(id=777, event='workflow_dispatch', status='queued')]
                return json.dumps(dict(total_count=101, workflow_runs=rows))
            return json.dumps(dict(total_count=0, workflow_runs=[]))
        with self.assertRaisesRegex(RuntimeError, '777'): active_cloud_writers(run=run)
        self.assertEqual(len(calls), 6)
        self.assertTrue(all('status=' in call for call in calls))

    def test_incomplete_inventory_refuses(self):
        run = lambda *a, **k: json.dumps(dict(total_count=101, workflow_runs=[]))
        with self.assertRaisesRegex(RuntimeError, 'incomplete'): active_cloud_writers(run=run, max_pages=1)


if __name__ == '__main__': unittest.main()


@__import__('pytest').mark.parametrize('value', [[], {}, {'workflow_runs':[], 'total_count':True},
    {'workflow_runs':[], 'total_count':-1}, {'workflow_runs':[{}], 'total_count':1}])
def test_malformed_writer_inventory_fails_closed_with_explicit_diagnostic(value):
    import pytest
    with pytest.raises(RuntimeError, match='malformed'):
        active_cloud_writers(run=lambda *a, **k: json.dumps(value))


def test_same_size_rewrite_with_restored_mtime_invalidates_cached_guard_pin(tmp_path):
    import os
    import pytest
    path = tmp_path / 'pin'; path.write_bytes(b'first')
    guard = RecoveryGuard(pins={path:hashlib.sha256(b'first').hexdigest()}, local_check=lambda:None,
        cloud_check=lambda:None, protected_check=lambda:None)
    guard.boundary(); before=path.stat()
    path.write_bytes(b'other'); os.utime(path, ns=(before.st_atime_ns,before.st_mtime_ns))
    with pytest.raises(RuntimeError, match='Pinned input changed'):
        guard.shared_commit()


@__import__('pytest').mark.parametrize('next_check', ['check', 'shared_commit'])
def test_changed_pin_is_rehashed_even_when_metadata_is_identical(tmp_path, monkeypatch, next_check):
    import pytest
    from corpus_recovery import guards
    path = tmp_path / 'pin'
    path.write_bytes(b'first')
    custody = guards._identity(path)
    monkeypatch.setattr(guards, '_identity', lambda candidate: custody)
    guard = RecoveryGuard(pins={path:hashlib.sha256(b'first').hexdigest()},
        local_check=lambda:None, cloud_check=lambda:None, protected_check=lambda:None)
    guard.boundary()
    path.write_bytes(b'other')
    with pytest.raises(RuntimeError, match='Pinned input changed'):
        getattr(guard, next_check)()


def test_remote_check_cannot_hide_same_metadata_pin_change(tmp_path, monkeypatch):
    import pytest
    from corpus_recovery import guards
    path = tmp_path / 'pin'
    path.write_bytes(b'first')
    custody = guards._identity(path)
    monkeypatch.setattr(guards, '_identity', lambda candidate: custody)
    guard = RecoveryGuard(pins={path:hashlib.sha256(b'first').hexdigest()},
        local_check=lambda:None, cloud_check=lambda:None,
        protected_check=lambda:path.write_bytes(b'other'))
    with pytest.raises(RuntimeError, match='Pinned input changed'):
        guard.shared_commit()
