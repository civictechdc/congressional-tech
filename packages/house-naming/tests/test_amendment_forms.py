"""Amendment form phrases retain wording without assigning document identity."""
import pytest

from house_naming import Engine
from house_naming.filenames import parse_filename


@pytest.fixture(scope='module')
def engine():
    return Engine()


def labels(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    assert parse_filename(name).model_dump(mode='json')['matches'] == result['observations']
    found = [m for m in result['observations'] if m['rule'] == 'amendment-form-wording']
    for match in found:
        field, = match['fields']
        assert field['name'] == 'label'
        assert name[field['start']:field['end']] == field['raw']
        assert field['start'] == match['start'] and field['end'] == match['end']
        assert field['code'] is None and field['label'] is None and field['candidates'] == []
        assert 'no official amendment identity' in match['description']
    return [m['fields'][0]['raw'] for m in found]


@pytest.mark.parametrize('name,phrase', [
    ('S. Con. Res. 10 Preamble Amendment.pdf', 'Preamble Amendment'),
    ('S. Res. 456_Resolving_Clause_Amendment.pdf', 'Resolving_Clause_Amendment'),
    ('H.R.1036_Substitute_Amendment.pdf', 'Substitute_Amendment'),
    ('S. Res. 97 Title Amendment1.pdf', 'Title Amendment'),
    ('S. Res. 371 Preamble Amendment REVISED.pdf', 'Preamble Amendment'),
    ('hr4550_substitute_amendmentpdf', 'substitute_amendment'),
    ('sres345-resolving-clause-amendment101921', 'resolving-clause-amendment'),
    # Constructed orthographic and extension controls.
    ('PreambleAmendment.pdf', 'PreambleAmendment'),
    ('TITLE AMENDMENT.xml', 'TITLE AMENDMENT'),
    ('ResolvingClauseAmendment.html.pdf', 'ResolvingClauseAmendment'),
    ('  Substitute-Amendment.pdf  ', 'Substitute-Amendment'),
    ('Preamble Amendmentpdf-2.pdf', 'Preamble Amendment'),
    ('Preamble Amendment.pdf?download=1', 'Preamble Amendment'),
])
def test_preserves_whole_phrase(engine, name, phrase):
    assert labels(engine, name) == [phrase]


@pytest.mark.parametrize('phrase', ['Preamble', 'Resolving Clause', 'Title', 'Substitute'])
def test_plural_phrase_keeps_existing_generic_label(engine, phrase):
    name = f'{phrase} Amendments.pdf'
    assert labels(engine, name) == [f'{phrase} Amendments']
    assert any(f['name'] == 'label' and f['raw'] == 'Amendments'
               for m in engine.extract(name)['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    "H.R.965_Manager's_Substitute_Amendment1.pdf",
    'S. Res. 165_Managers_Preamble_Amendment.pdf',
    "S. Res. 122 Manager's Resolving Clause Amendment.pdf",
    'sres20_managers_title_amendment',
])
def test_does_not_duplicate_more_specific_manager_phrase(engine, name):
    assert not labels(engine, name)
    assert any(m['rule'] == 'managers-amendment-wording'
               for m in engine.extract(name)['observations'])


@pytest.mark.parametrize('name', [
    'Notitle Amendment.pdf', 'InterSubstituteAmendment.pdf',
    'Preamble Amendmentsmith.pdf', 'TitleAmendmentary.pdf',
    'SubstituteAmendmentation.pdf', 'ResolvingClauseAmendmentExtra.pdf',
    'PreamblesAmendment.pdf', 'PreambleAmend.pdf',
    'Preamble for Amendment.pdf', 'Amendment to the Preamble.pdf',
    'éPreambleAmendment.pdf', '١PreambleAmendment.pdf',
    'PreambleAmendmenté.pdf', '%20PreambleAmendment.pdf', '%PreambleAmendment.pdf',
    'HHRG-119-IF00-Wstate-PreambleAmendment-20260101.pdf',
    'BILLS-119-HR1-A000001-Amdt-TitleAmendment.pdf',
    'download.pdf?label=SubstituteAmendment',
])
def test_boundaries_and_owned_slots(engine, name):
    assert not labels(engine, name)


@pytest.mark.parametrize('number', ['1', '01', '111111', '12345'])
def test_numbered_amendment_keeps_its_existing_identifier(engine, number):
    name = f'Title Amendment{number}.pdf'
    assert labels(engine, name) == ['Title Amendment']
    fields = [f for m in engine.extract(name)['observations'] for f in m['fields']]
    assert any(f['name'] == 'amendment_token' and f['raw'] == number for f in fields)
    assert not any(f['name'] in {'date_token', 'short_date_token'} for f in fields)


def test_multiple_form_phrases_have_distinct_spans(engine):
    name = 'Preamble Amendment and Title Amendment.pdf'
    assert labels(engine, name) == ['Preamble Amendment', 'Title Amendment']
    result = engine.extract(name)
    assert not any(f['name'] in {'amendment_token', 'bioguide_token', 'congress'}
                   for m in result['observations'] for f in m['fields'])
