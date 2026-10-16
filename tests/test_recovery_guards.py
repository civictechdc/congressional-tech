import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recovery_guards import RecoveryGuard, active_cloud_writers


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'input'; self.path.write_bytes(b'sealed')
        self.local, self.cloud, self.protected = Mock(), Mock(), Mock()
        self.now = 0
        self.guard = RecoveryGuard(pins={self.path: hashlib.sha256(b'sealed').hexdigest()},
            local_check=self.local, cloud_check=self.cloud, protected_check=self.protected,
            clock=lambda: self.now)

    def test_many_immutable_writes_share_only_expensive_clearance(self):
        self.guard.boundary()
        for _ in range(1000): self.guard.check()
        self.assertEqual(self.guard.counts, dict(local=1001, hashed_files=1, cloud=1, protected=1))
        self.guard.shared_commit()
        self.assertEqual(self.guard.counts, dict(local=1002, hashed_files=2, cloud=2, protected=2))

    def test_unknown_cloud_invalidates_allowance(self):
        self.guard.check(); self.now = 31
        self.cloud.side_effect = TimeoutError('unknown')
        for _ in range(2):
            with self.assertRaises(TimeoutError): self.guard.check()
        self.assertEqual(self.cloud.call_count, 3)
        self.cloud.side_effect = None
        self.guard.check(); self.assertEqual(self.cloud.call_count, 4)

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
