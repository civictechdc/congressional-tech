"""Raw recurring cases and controls from the retained filename inventory."""
import pytest

from house_naming import Engine
from house_naming.extraction import date_candidates


@pytest.fixture(scope='module')
def engine():
    return Engine()


def fields(result, name, rule=None):
    return [f for m in result['observations'] if rule is None or m['rule']==rule
            for f in m['fields'] if f['name']==name]


@pytest.mark.parametrize('name,label', [
    ('brown-statement-040924', 'statement'),
    ('Brown Statement 1-11-22.pdf', 'Statement'),
    ('07112018-brown-statement', 'statement'),
    ('business-meeting-01-20-2025', 'business-meeting'),
    ('05 13 20 -- Nominations.pdf', 'Nominations'),
    ('BILLS-115-OversightPlan-F000454-Amdt-016.pdf', 'OversightPlan'),
])
def test_literal_labels_survive_inside_date_or_legislative_names(engine, name, label):
    result = engine.extract(name)
    assert label in [f['raw'] for f in fields(result,'label')]
    for field in fields(result,'label'):
        assert name[field['start']:field['end']]==field['raw']
        assert field['code'] is None  # No document-content classification.


@pytest.mark.parametrize('name', ['understatement.pdf','reStatementSuffix.pdf','renominations.pdf','BusinessMeetingness.pdf'])
def test_labels_do_not_match_arbitrary_word_interiors(engine, name):
    result = engine.extract(name)
    assert not fields(result,'label')


@pytest.mark.parametrize('name,expected_name,expected_value,subject', [
    ('012125-crapo-statement','date_token','012125','crapo'),
    ('0209-crapo-statement','generic_identifier','0209','crapo'),
    ('Statement for the Record from Russell Coleman 6.21.21.pdf','date_token','6.21.21','for the Record from Russell Coleman'),
])
def test_new_label_keeps_date_identifier_and_subject_separation(engine, name, expected_name, expected_value, subject):
    result=engine.extract(name)
    refined=[m for m in result['observations'] if m['scope']=='subject-refinement']
    values={f['name']:f['raw'] for m in refined for f in m['fields']}
    assert values[expected_name]==expected_value and values['subject_token']==subject
    for m in refined:
        for f in m['fields']:
            assert name[f['start']:f['end']]==f['raw']


@pytest.mark.parametrize('raw,expected', [
    ('1032018', ['2018-01-03','2018-03-01','2018-03-10','2018-10-03']),
    ('2024113', ['2024-01-13','2024-11-03']),
    ('9992023', []),
])
def test_seven_digit_dates_preserve_every_valid_supported_order(raw, expected):
    values,valid,_ = date_candidates(raw)
    assert values==expected and valid==bool(expected)


def test_transcript_date_stays_a_candidate_and_does_not_create_a_person(engine):
    name='official-hearing-transcript_1032018'
    result=engine.extract(name)
    dates=fields(result,'date_token','date-compact-unpadded')
    assert dates[0]['raw']=='1032018'
    assert len(dates[0]['candidates'])==4
    assert not fields(result,'name_token')


def test_unpadded_leading_date_precedes_generic_identifier_fallback(engine):
    result=engine.extract('1032018-Smith.pdf')
    assert fields(result,'date_token','unmatched-leading-date')[0]['raw']=='1032018'
    assert not fields(result,'generic_identifier')
    assert fields(result,'name_token')[0]['raw']=='Smith'


def test_date_after_invalid_numeric_prefix_is_not_skipped(engine):
    result=engine.extract('19-13_02-14-19')
    assert [f['raw'] for f in fields(result,'date_token','date-separated')]==['02-14-19']
    assert any(m['raw']=='19-13_02' and m['reason']=='No valid supported calendar reading.' for m in result['suppressed'])
    assert any(m['raw']=='13_02-14' and m['reason']=='Overlaps a structured or already assigned token.' for m in result['suppressed'])


def test_isolated_mixed_separator_date_remains_inspectable(engine):
    result=engine.extract('Smith-2024-02_29.pdf')
    assert fields(result,'date_token','date-separated')[0]['candidates']==['2024-02-29']


def test_structured_person_ids_are_not_seven_digit_dates(engine):
    result=engine.extract('HHRG-119-AS00-Wstate-S000522-20260101.pdf')
    assert not fields(result,'date_token','date-compact-unpadded')
    result=engine.extract('BILLS-119HR1032018ih.pdf')
    assert not fields(result,'date_token','date-compact-unpadded')


@pytest.mark.parametrize('subject,marker,identifier', [
    ('CommitteePrintSubtitleD','Subtitle','D'),
    ('CommitteePrintTitleIV','Title','IV'),
    ('CommitteePrintDivision12','Division','12'),
    ('CommitteePrint',None,None),
])
def test_print_subject_keeps_its_section_without_inventing_a_bill(engine, subject, marker, identifier):
    name=f'BILLS-119-{subject}-A000370-Amdt-116.pdf'
    result=engine.extract(name)
    match=next(m for m in result['observations'] if m['rule']=='committee-print-subject')
    actual={f['name']:f['raw'] for f in match['fields']}
    assert actual['label']=='CommitteePrint'
    assert actual.get('section_marker')==marker
    assert actual.get('section_identifier')==identifier
    assert not fields(result,'measure_number')


def test_print_subject_rule_stays_inside_its_legislative_slot(engine):
    assert not fields(engine.extract('UnrelatedCommitteePrintSubtitleD.pdf'),'section_identifier')
    assert not fields(engine.extract('BILLS-119-NotCommitteePrintSubtitleD-A000370-Amdt-116.pdf'),'section_identifier')
