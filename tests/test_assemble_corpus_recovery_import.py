"""Verify ZIP coverage and separation of retained availability from retry state."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('assemble_recovery', Path(__file__).resolve().parents[1]
                                            / 'scripts/assemble_corpus_recovery_import.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.url = 'https://example.org/archive.zip'
        self.item = dict(original_url=self.url, preserve_download_state=True,
                         record=dict(url=self.url, retrieved_at='2020-01-02T00:00:00Z',
                                     content=dict(sha256='parent', body=None),
                                     source_associations=[dict(original_url=self.url)],
                                     archive_members=[dict(original_name='a.pdf',
                                         parent_archive_body_key='parent-key',
                                         content=dict(sha256='member', body=None))]), captures=[])
        self.bodies = {}
        for digest, pointer in [('parent', ['content', 'body']),
                                ('member', ['archive_members', 0, 'content', 'body'])]:
            cap = dict(body_key=digest+'-key', sha256=digest, bytes=10,
                       context_url=self.url, pointer=pointer, retrieved_at='2020-01-02T00:00:00Z')
            if digest == 'member':
                cap['original_path'] = 'a.pdf'
            self.item['captures'].append(cap)
            self.bodies[cap['body_key']] = dict(body_key=cap['body_key'], sha256=digest,
                bytes=10, stored_sha256='stored-'+digest, stored_bytes=20)

    def test_all_zip_captures_and_failed_state_survive(self):
        old = {self.url: dict(url=self.url, outcome='failed', attempts=7,
                             next_attempt_at='2030-01-01', custom_evidence=['keep'])}
        before = deepcopy(old)
        receipts, states = module.assemble([self.item], old, self.bodies, 'recovery')
        self.assertEqual(states, before)
        self.assertEqual(old, before)
        self.assertEqual(receipts[0]['download_state'], before[self.url])
        rows = module.index_rows(receipts, 'receipts/example.jsonl.gz')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['original_path'], 'a.pdf')
        self.assertEqual(rows[1]['receipt_line'], 1)
        self.assertEqual(rows[1]['resolution'], 'saved')
        self.assertEqual(rows[1]['pointer_json'], '["archive_members", 0, "content", "body"]')

    def test_new_source_stays_pending(self):
        receipts, states = module.assemble([self.item], {}, self.bodies, 'recovery')
        self.assertEqual(states[self.url]['outcome'], 'pending')
        self.assertIsNone(states[self.url]['body_key'])
        self.assertEqual(states[self.url]['attempts'], 0)

    def test_corrupt_body_metadata_rejected(self):
        self.bodies['member-key']['sha256'] = 'wrong'
        with self.assertRaises(ValueError):
            module.assemble([self.item], {}, self.bodies, 'recovery')

    def test_wrong_member_parent_rejected(self):
        self.item['record']['archive_members'][0]['parent_archive_body_key'] = 'wrong'
        with self.assertRaises(ValueError):
            module.assemble([self.item], {}, self.bodies, 'recovery')

    def test_missing_source_association_rejected(self):
        self.item['record']['source_associations'] = []
        with self.assertRaises(ValueError):
            module.assemble([self.item], {}, self.bodies, 'recovery')


if __name__ == '__main__':
    unittest.main()


def test_assembly_copies_only_accessed_baseline_rows():
    class Unused:
        def __deepcopy__(self, memo):
            raise AssertionError('Unrelated baseline row copied')
    fixture = AssemblyTests()
    fixture.setUp()
    baseline = {'unused': Unused(), fixture.url: dict(url=fixture.url, outcome='failed', nested=[None, {'value': 7}])}
    receipts, states = module.assemble([fixture.item], baseline, fixture.bodies, 'test')
    states[fixture.url]['nested'][1]['value'] = 8
    assert baseline[fixture.url]['nested'][1]['value'] == 7
    assert receipts[0]['download_state']['nested'][1]['value'] == 7
    assert len(states) == 2


def test_duplicate_prepared_urls_share_one_pending_state_and_keep_both_receipts():
    fixture = AssemblyTests()
    fixture.setUp()
    receipts, states = module.assemble([fixture.item, fixture.item], {}, fixture.bodies, 'test')
    assert len(receipts) == 2
    assert len(states) == 1
    assert len(module.index_rows(receipts, 'test')) == 4
