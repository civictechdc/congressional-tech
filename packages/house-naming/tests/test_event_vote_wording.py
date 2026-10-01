"""Observed event/vote gaps and constructed genre/identifier boundaries."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, filename):
    result = engine.extract(filename)
    assert ''.join(part['raw'] for part in result['pieces']) == filename
    for observation in result['observations']:
        for field in observation['fields']:
            assert filename[field['start']:field['end']] == field['raw']
    assert all(result[key] == value for key, value in engine.parse(filename).items())
    return result['metadata']


@pytest.mark.parametrize('tally', ['11-9', '12-8', '16-4'])
@pytest.mark.parametrize('extension', ['pdf', 'xml'])
def test_vote_tally_does_not_supply_the_date_year(engine, tally, extension):
    row = checked(engine, f'07.21 {tally} vote.{extension}')
    assert row['document_kind'] == ['vote-record']
    assert row['possible_month_day_token'] == ['07.21']
    assert row['vote_tally_token'] == [tally]
    assert row['vote_wording'] == ['vote']
    assert not row.get('date_token')
    assert not row.get('generic_identifier')
    assert not row.get('vote_date')
    assert not row.get('vote_id')
    assert not row.get('year_token')


@pytest.mark.parametrize('name', [
    '07.21.2011 Vote.pdf', '07.21 11-9 voter.pdf',
    '07.21 11-9 Vote Act.pdf', 'HR11-9.pdf', 'Vote.pdf',
    '07.21 11-9 vote policy.pdf',
])
def test_vote_record_requires_complete_observed_layout(engine, name):
    row = checked(engine, name)
    assert 'vote-record' not in row.get('document_kind', [])
    assert not row.get('vote_tally_token')


@pytest.mark.parametrize('name,kind,wording,subject', [
    ('0725-Panel-Discussion-A-Dark-Place-edited.pdf', 'panel-discussion', 'Panel-Discussion', 'A-Dark-Place'),
    ('10.07.19 President Nez Field Hearing.pdf', 'field-hearing', 'Field Hearing', 'President Nez'),
    ('Grassley-Field-Hearing.docx', 'field-hearing', 'Field-Hearing', 'Grassley'),
    ('21A895229D07CF5FB5CC32A387EF7AF7AFEB739CE5AFCF97DF0C804B12671C81.fieldhearing-pdftran.pdf',
     'field-hearing', 'fieldhearing', 'pdftran'),
])
def test_event_wording_is_an_explicit_fallback(engine, name, kind, wording, subject):
    row = checked(engine, name)
    assert row['document_kind'] == [kind]
    assert row['meeting_wording'] == [wording]
    assert row['meeting_wording_code'] == [kind]
    assert subject in row['subject_token']
    assert not row.get('meeting_type')
    assert not row.get('witness_id')


@pytest.mark.parametrize('name,kind,event', [
    ('02-16-Panel-Discussion-Aferim-Bravo-Transcript.pdf', 'transcript', 'panel-discussion'),
    ('02.21 Field Hearing Testimony.pdf', 'testimony', 'field-hearing'),
    ('FieldHearingTestimony_Goble_Final.pdf', 'testimony', 'field-hearing'),
    ('07-22-19_field_hearing_notice.pdf', 'meeting-notice', 'field-hearing'),
    ('3.1.24 Baldwin Opening Statement Field Hearing.pdf', 'opening-statement', 'field-hearing'),
    ('Report on Field Hearing Procedures.pdf', 'report', 'field-hearing'),
    ('Report on Panel Discussion Techniques.pdf', 'report', 'panel-discussion'),
])
def test_specific_genre_keeps_event_as_context(engine, name, kind, event):
    row = checked(engine, name)
    assert row['document_kind'] == [kind]
    assert event in row['meeting_wording_code']


@pytest.mark.parametrize('name', [
    'HHRG-119-IF00-Wstate-FieldHearing-20250318.pdf',
    'HHRG-119-IF00-Wstate-PanelDiscussion-20250318.pdf',
    'FieldHearingston.pdf', 'PanelDiscussionary.pdf',
])
def test_names_and_structured_witness_slots_are_not_event_context(engine, name):
    row = checked(engine, name)
    assert not row.get('meeting_wording')
    assert not {'panel-discussion', 'field-hearing'} & set(row.get('document_kind', []))


@pytest.mark.parametrize('name', [
    'BILLS-119-HR123-Field-Hearing-Procedures-ih.pdf',
    'BILLS-119-HR123-Panel-Discussion-Act-ih.pdf',
])
def test_bill_title_event_words_do_not_change_document_kind(engine, name):
    row = checked(engine, name)
    assert not {'panel-discussion', 'field-hearing'} & set(row.get('document_kind', []))


def test_nomination_vote_transcript_remains_a_transcript(engine):
    row = checked(engine, '06092016 - Transcript - Dr. Hayden Nomination Vote.pdf')
    assert row['document_kind'] == ['transcript']
    assert not row.get('vote_tally_token')
