"""Exercise concurrent mapping changes without any remote writes."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

import corpus_recovery.mappings as module


def document(**rows):
    return dict(version=1, recoveries=[dict(original_url=url, body_key=body)
                                     for url, body in rows.items()])


class MergeTests(unittest.TestCase):
    def test_fresh_edits_additions_deletions_and_metadata_survive(self):
        baseline = document(old='v1', removed='gone')
        prepared = document(old='v1', removed='gone', recovered='new')
        fresh = document(old='v2', concurrent='other')
        fresh['evidence'] = {'keep': ['yes']}
        snapshot = deepcopy((baseline, prepared, fresh))
        result = module.merge_mappings(baseline, prepared, fresh)
        self.assertEqual({r['original_url']: r['body_key'] for r in result['recoveries']},
                         dict(old='v2', concurrent='other', recovered='new'))
        self.assertEqual(result['evidence'], fresh['evidence'])
        result['evidence']['keep'].append('result-only')
        self.assertEqual((baseline, prepared, fresh), snapshot)

    def test_identical_concurrent_addition_is_idempotent(self):
        self.assertEqual(module.merge_mappings(document(), document(a='x'), document(a='x')),
                         document(a='x'))

    def test_conflicting_new_recovery_stops(self):
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            module.merge_mappings(document(), document(a='x'), document(a='y'))

    def test_prepared_cannot_edit_or_remove_baseline(self):
        for prepared in (document(), document(a='changed')):
            with self.assertRaisesRegex(ValueError, 'changes a baseline'):
                module.merge_mappings(document(a='original'), prepared, document(a='fresh'))

    def test_duplicate_or_unknown_version_stops(self):
        bad = document(a='x')
        bad['recoveries'] *= 2
        for value in (bad, dict(version=2, recoveries=[])):
            with self.assertRaises(ValueError):
                module.merge_mappings(document(), document(), value)


if __name__ == '__main__':
    unittest.main()
