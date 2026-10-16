from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import run_corpus_recovery as runner

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name).resolve(); self.dest = self.cwd/'run'
    def prepare(self, code='print(42)', resume=None):
        return runner.prepare(self.dest,cwd=self.cwd,
            command=[sys.executable,'-c',code],
            resume_command=[sys.executable,'-c',resume] if resume else None,reserve_bytes=0)
    def test_actual_wait_and_cwd(self):
        self.prepare('import os; print(os.getcwd())')
        self.assertEqual(runner.run(self.dest,interval=.01),0)
        self.assertTrue(runner.status(self.dest)['complete'])
        self.assertEqual((self.dest/'attempt-0001/stdout.log').read_text().strip(),str(self.cwd))
        with self.assertRaises(RuntimeError): runner.run(self.dest)
    def test_failure_never_restarts_and_requires_explicit_resume(self):
        self.prepare('raise SystemExit(7)', 'print("resumed")')
        self.assertEqual(runner.run(self.dest,interval=.01),7)
        self.assertEqual(runner.status(self.dest)['attempts'],1)
        self.assertFalse(runner.reconcile(self.dest)['complete'])
        with self.assertRaises(RuntimeError): runner.run(self.dest)
        self.assertEqual(runner.run(self.dest,resume=True,interval=.01),0)
    def test_changed_plan_and_pin_block(self):
        p=self.cwd/'source';p.write_text('old')
        runner.prepare(self.dest,cwd=self.cwd,command=[sys.executable,'-c','pass'],pins=[p],reserve_bytes=0)
        p.write_text('new')
        with self.assertRaisesRegex(ValueError,'Pinned'):runner.run(self.dest)
    def test_reused_pid_is_not_same_process(self):
        record=dict(pid=1,parent_pid=0,started='old',command='old')
        with patch.object(runner,'identity',return_value=dict(record,started='new')):
            self.assertFalse(runner.same_process(record))
    def test_reparented_child_remains_live(self):
        record=dict(pid=12,parent_pid=11,started='same',command='worker')
        with patch.object(runner,'identity',return_value=dict(record,parent_pid=1)):
            self.assertTrue(runner.same_process(record))
    def test_missing_wait_is_never_success(self):
        self.prepare();self.assertEqual(runner.run(self.dest,interval=.01),0)
        (self.dest/'attempt-0001/exit.json').unlink()
        with patch.object(runner,'same_process',return_value=False):
            self.assertEqual(runner.reconcile(self.dest)['state'],'requires_reconciliation')
            self.assertFalse(runner.reconcile(self.dest)['complete'])
    def test_incomplete_dispatch_never_allows_second_child(self):
        self.prepare(resume='pass')
        (self.dest/'attempt-0001').mkdir()
        with self.assertRaisesRegex(RuntimeError,'identity was not recorded'):
            runner.run(self.dest,resume=True,interval=.01)
    def test_dispatch_record_failure_reaps_child(self):
        self.prepare('import time; time.sleep(30)')
        original=runner.atomic
        def atomic(path,value):
            if Path(path).name=='dispatch.json':raise OSError('record failed')
            original(path,value)
        with patch.object(runner,'atomic',side_effect=atomic):
            with self.assertRaisesRegex(OSError,'record failed'):runner.run(self.dest,interval=.01)
        self.assertTrue((self.dest/'attempt-0001/exit.json').exists())
    def test_relative_executable_is_rejected(self):
        with self.assertRaises(ValueError):runner.prepare(self.dest,cwd=self.cwd,command=['python','-c','pass'])

if __name__=='__main__':unittest.main()
