"""Real questionnaire and biography labels, plus constructed boundary controls."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for match in (*result['observations'], *result['suppressed']):
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
    return result


def fields(result, name, rule=None):
    return [f for m in result['observations'] if rule is None or rule == m['rule']
            for f in m['fields'] if f['name'] == name]


def values(result, name, rule=None):
    return [f['raw'] for f in fields(result, name, rule)]


@pytest.mark.parametrize('name,label', [
    ('ARTAU SJQ.pdf', 'SJQ'),
    ('Andrew Brasher Senate Questionnaire (PUBLIC)_fb4b37e5-0157-4131-86d9-f6e3bbee9e4e.pdf', 'Senate Questionnaire'),
    ('Cronan Senate Judiciary Questionnaire (PUBLIC)_3de564db-4eab-4cd6-831d-4b55c9bc4631.pdf', 'Senate Judiciary Questionnaire'),
    ('Baker APQ Responses1.pdf', 'APQ Responses'),
    ('Berger APQ Responses.pdf', 'APQ Responses'),
    ('Blume APQ responses.pdf', 'APQ responses'),
    ('Calvelli APQ Rsponses.pdf', 'APQ'),  # Do not repair the source typo.
    ('smith_apqs.pdf', 'apqs'),  # Constructed plural.
    ('Smith Advance Policy Questions.pdf', 'Advance Policy Questions'),
    ('Smith Advance Questions.pdf', 'Advance Questions'),
    ('smith-senate-questionnairepdf', 'senate-questionnaire'),
])
def test_observed_and_constructed_questionnaire_labels(engine, name, label):
    result = checked(engine, name)
    assert values(result, 'label', 'questionnaire-wording') == [label]
    assert not fields(result, 'document_token')
    assert fields(result, 'label', 'questionnaire-wording')[0]['context'] is None


@pytest.mark.parametrize('name,label', [
    ('2023-03-08 - Bio & Testimony - Farid.pdf', 'Bio'),
    ('Bios-Human-Rights-at-Home-External.pdf', 'Bios'),
    ('Witness-Bios-for-Web_Counter-Kleptocracy-Hearing.pdf', 'Witness-Bios'),
    ('Paul Smith CV April 2021.pdf', 'CV'),
    ('Kyle David Andeer Resume.pdf', 'Resume'),
    ('MAUREEN RIORDAN Resume (62621).pdf', 'Resume'),
    ('maureen-riordan-resume-62621pdf', 'resume'),
    ('Smith Curriculum Vitae.pdf', 'Curriculum Vitae'),
    ('Smith C.V..pdf', 'C.V.'),
    ('Smith Résumé.pdf', 'Résumé'),
    ('Smith Biographies.pdf', 'Biographies'),
    ('smith-biopdf', 'bio'),
])
def test_observed_and_constructed_biographical_wording(engine, name, label):
    result = checked(engine, name)
    assert values(result, 'label', 'biographical-wording') == [label]
    assert fields(result, 'label', 'biographical-wording')[0]['context'] is None
    if 'Testimony' in name:
        assert 'Testimony' in values(result, 'label')


@pytest.mark.parametrize('name,words', [
    ('2019.SJQ.Rosen_Public_Final_421cdd79-4654-43d1-8644-cff6955963be.pdf', ['Public', 'Final']),
    ('Abelson SJQ Public Final_7acd5e4b-6675-42a7-98df-4424fb396424.pdf', ['Public', 'Final']),
    ('Beaton Public SJQ_f1f1d7c9-c09e-40b2-9280-5be6c3aeea1d.pdf', ['Public']),
    ('Brantley Starr Senate Questionnaire (PUBLIC) - OCR_4e892875-36dd-4df7-9d2e-f567e8333e20.pdf', ['PUBLIC', 'OCR']),
    ('Smith Public Final SJQ.pdf', ['Public', 'Final']),
    ('Smith SJQ (PUBLIC) - FINAL - REDACTED.pdf', ['PUBLIC', 'FINAL', 'REDACTED']),
    ('Smith Bio Final.pdf', ['Final']),
    ('Freeman SJQ Public Final1_26d51c57-c0a4-4277-a7eb-7813d022c78d.pdf', ['Public', 'Final']),
    ('freeman-sjq-public-final1pdf', ['public', 'final']),
    ('Public Health Questionnaire.pdf', []),
    ('Final report discusses Smith SJQ.pdf', []),
    ('Smith SJQ about Public Health.pdf', []),
    ('SJQ answers about Final Assessment.pdf', []),
])
def test_only_adjacent_qualifier_words_receive_fields(engine, name, words):
    result = checked(engine, name)
    assert values(result, 'qualifier_wording') == words
    for field in fields(result, 'qualifier_wording'):
        assert field['code'] is None and field['context'] is None
        assert 'not verified' in field['note']
    assert not fields(result, 'status')


@pytest.mark.parametrize('name,number', [
    ('Baker APQ Responses1.pdf', '1'), ('Cotton APQ responses5.pdf', '5'),
    ('Smith Bio02.pdf', '02'), ('smith_apq_responses01pdf-1', '01'),
    ('freeman-sjq-public-final1pdf', '1'),
    ('rearden-sjq-public1pdf', '1'),
])
def test_adjacent_digits_remain_whole_local_components(engine, name, number):
    result = checked(engine, name)
    assert values(result, 'local_number_token', 'document-label-number') == [number]
    assert 'not an established bill or amendment sequence' in fields(result, 'local_number_token', 'document-label-number')[0]['note']


@pytest.mark.parametrize('value', ['121119', '20250318', '20250318123145'])
def test_date_shaped_numbers_keep_existing_priority(engine, value):
    result = checked(engine, f'Smith APQ Responses{value}.pdf')
    assert values(result, 'label', 'questionnaire-wording') == ['APQ Responses']
    assert not fields(result, 'local_number_token', 'document-label-number')
    assert any(fields(result, k) for k in ('date_token','short_date_token'))


@pytest.mark.parametrize('name', [
    'ASJQ.pdf', 'APQRS.pdf', 'SJQuery.pdf', 'biotechnology.pdf', 'bioscience.pdf',
    'resumeable.pdf', 'CVS.pdf', 'HHRG-119-IF00-Bio-SJQAPQ-20250318.pdf',
    'HHRG-119-IF00-Wstate-Bio-20250318.pdf',
])
def test_embedded_words_and_structured_house_fields_stay_protected(engine, name):
    result = checked(engine, name)
    assert not fields(result, 'label', 'questionnaire-wording')
    assert not fields(result, 'label', 'biographical-wording')


def test_structured_bio_keeps_its_existing_vocabulary_meaning(engine):
    result = checked(engine, 'HHRG-119-IF00-Bio-SmithJ-20250318.pdf')
    assert values(result, 'document_token') == ['Bio']
    assert fields(result, 'document_token')[0]['code'] == 'bio'
    assert not fields(result, 'label', 'biographical-wording')
    assert not any(m['rule'] == 'biographical-wording' for m in result['suppressed'])


def test_existing_biography_label_is_not_duplicated(engine):
    result = checked(engine, 'Smith Biography.pdf')
    assert values(result, 'label') == ['Biography']


@pytest.mark.parametrize('name', ['Smith Biography Final.pdf', 'Biography Smith Final.pdf'])
def test_existing_biography_layouts_share_qualifier_recognition(engine, name):
    result = checked(engine, name)
    assert values(result, 'label') == ['Biography']
    assert values(result, 'qualifier_wording') == ['Final']


def test_existing_biography_wording_shares_number_recognition(engine):
    result = checked(engine, 'Smith Biography02.pdf')
    assert values(result, 'label') == ['Biography']
    assert values(result, 'local_number_token', 'document-label-number') == ['02']


def test_real_uuid_stays_intact(engine):
    result = checked(engine, 'Abelson SJQ Public Final_7acd5e4b-6675-42a7-98df-4424fb396424.pdf')
    assert values(result, 'opaque_uuid') == ['7acd5e4b-6675-42a7-98df-4424fb396424']
