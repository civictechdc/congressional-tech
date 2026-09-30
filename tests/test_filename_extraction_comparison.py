"""The head-to-head check must see differences hidden by equal code tokens."""
from compare_filename_extraction import field_metadata
from compare_filename_extraction import strict_results_equal
from compare_filename_extraction import reviewed_strict_change


def test_diagnostic_allowance_cannot_hide_changed_acceptance_or_records():
    before = {'valid': False, 'matches': [], 'issues': ['no-matching-convention']}
    after = {**before, 'issues': ['invalid-calendar-date', 'no-matching-convention'],
             'rejected_candidates': [{'code': 'invalid-calendar-date'}]}
    assert strict_results_equal(before, after, allow_diagnostics=True)
    assert not strict_results_equal(before, after)
    assert not strict_results_equal(before, {**after, 'valid': True}, allow_diagnostics=True)
    assert not strict_results_equal(before, {**after, 'matches': [{'record': {}}]}, allow_diagnostics=True)
    assert not strict_results_equal(before, {**after, 'issues': ['invalid-calendar-date']}, allow_diagnostics=True)


def test_reviewed_correction_requires_exact_inputs_outputs_and_reason():
    before = {'matches': [{'record': {'measureNumber': 2534116}}], 'issues': []}
    after = {'matches': [{'record': {'description': 'HR2534116thCongress'}}],
             'issues': ['ambiguous-number-boundary']}
    review = {'before': before, 'after': after, 'reason': 'Source digits have no established boundary.'}
    assert reviewed_strict_change(before, after, review)
    assert not reviewed_strict_change(before, after, None)
    assert not reviewed_strict_change(before, after, {**review, 'reason': ''})
    assert not reviewed_strict_change({**before, 'valid': True}, after, review)
    assert not reviewed_strict_change(before, {**after, 'issues': []}, review)
    assert not reviewed_strict_change(before, before, {**review, 'after': before})


def test_same_code_with_different_meaning_metadata_is_not_equal():
    field = dict(name='amendment_marker', raw='HAmdt', start=0, end=5,
                 code='hamdt2', label='HAmdt2', note=None, candidates=[])
    before = field_metadata([{'fields': [field]}])
    after = field_metadata([{'fields': [dict(field, label='House amendment (second degree)',
                                            note='Not a floor amendment number.', candidates=['hamdt2'])]}])
    key = ('amendment_marker', 'HAmdt', 0, 5)
    assert before[key]['code'] == after[key]['code']
    for attribute in ('label', 'note', 'candidates'):
        assert before[key][attribute] != after[key][attribute]


def test_multiple_meanings_of_one_source_span_survive_in_either_order():
    plain = dict(name='document_marker', raw='SD', start=0, end=2,
                 code=None, label=None, note=None, candidates=[])
    typed = dict(plain, code='sd', label='Supporting document for witness statement')
    before = field_metadata([{'fields': [plain]}, {'fields': [typed]}])
    reordered = field_metadata([{'fields': [typed]}, {'fields': [plain]}])
    assert before == reordered
    assert before != field_metadata([{'fields': [plain]}])
    assert before != field_metadata([{'fields': [typed]}])
