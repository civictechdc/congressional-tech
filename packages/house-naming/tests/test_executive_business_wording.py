"""Full meeting headings and context-dependent abbreviations retain exact text."""
import pytest
from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    matches = [m for m in result['observations'] if m['rule'] == 'executive-business-wording']
    for match in matches:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
            assert field['code'] is None and field['context'] is None and not field['candidates']
            assert 'no event identity, occurrence, attendance or access status is verified' in field['note']
    return result, matches


@pytest.mark.parametrize('name,raw', [
    ('01.09.2020 Results of Executive Business Meeting.pdf', 'Executive Business Meeting'),
    ('06-01-23-executive-business-meeting', 'executive-business-meeting'),
    ('02-09-22 Budget Executive Business Meeting3.pdf', 'Executive Business Meeting'),
    ('results-of-executive-business-meetings-10721', 'executive-business-meetings'),
    ('executive-business-meeting-transcript&download=1', 'executive-business-meeting'),
    ('Executive_Business_Meeting.pdf', 'Executive_Business_Meeting'),
    ('Executive Business Meetingpdf', 'Executive Business Meeting'),
    ('Executive Business Meetingpdf.pdf', 'Executive Business Meeting'),
    ('Executive Business Meeting1.pdf', 'Executive Business Meeting'),
])
def test_complete_phrase(engine, name, raw):
    _, matches = checked(engine, name)
    match, = matches
    field, = match['fields']
    assert (field['name'], field['raw'], field['label']) == ('meeting_wording', raw, 'Executive business meeting')


@pytest.mark.parametrize('name,raw', [
    ('2021-03-01-ebm-results', 'ebm'),
    ('2023-06-01 - EBM - Results.pdf', 'EBM'),
    ('20260205_EBM_Results.pdf', 'EBM'),
    ('Results of EBM.pdf', 'EBM'),
    ('Results of the EBM.pdf', 'EBM'),
    ('2025-01-29_ebm_resultspdf', 'ebm'),
    ('EBM Results - 2022-02-10.pdf', 'EBM'),
])
def test_abbreviation_requires_results_heading(engine, name, raw):
    _, matches = checked(engine, name)
    match, = matches
    field, = match['fields']
    assert (field['name'], field['raw'], field['label']) == ('meeting_abbreviation', raw, None)
    assert 'without expansion' in field['note']


@pytest.mark.parametrize('name', [
    'EBM.pdf', 'EBM research.pdf', 'Clinical EBM Study Results.pdf', 'EBMResults.pdf',
    'Results of EBMology.pdf', 'Executive Business Meetingship.pdf',
    'ExecutiveBusinessMeeting.pdf', 'NonExecutive Business Meeting.pdf',
    'Executive Summary.pdf', 'Executive Business.pdf', 'Executive Session.pdf',
    'Topic%20Executive Business Meeting.pdf', 'Topic%20EBM Results.pdf',
    'HHRG-119-IF00-Wstate-Executive Business Meeting-20250318.pdf',
    'HHRG-119-IF00-Wstate-EBM Results-20250318.pdf',
])
def test_nonmeeting_prose_and_protected_slots(engine, name):
    _, matches = checked(engine, name)
    assert matches == []


@pytest.mark.parametrize('access', ['Open', 'Closed'])
def test_explicit_access_is_wording_only(engine, access):
    result, matches = checked(engine, f'Results of {access} Executive Business Meeting on May 24, 2018.pdf')
    match, = matches
    assert [(f['name'], f['raw']) for f in match['fields']] == [
        ('access_wording', access), ('meeting_wording', 'Executive Business Meeting')]
    fields = [f for m in result['observations'] for f in m['fields']]
    assert any(f['name'] == 'date_token' and f['candidates'] == ['2018-05-24'] for f in fields)
    assert any(f['name'] == 'label' and f['raw'] == 'Business Meeting' for f in fields)
    assert any(f['name'] == 'result_wording' for f in fields)
    assert not any(f['name'] in {'meeting_status', 'access_status', 'vote_result'} for f in fields)
