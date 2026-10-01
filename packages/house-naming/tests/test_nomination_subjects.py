"""Nomination headings supply subjects, not established witness identities."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def extracted(engine, name):
    result = engine.extract(name)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    fields = {}
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
            fields.setdefault(field['name'], []).append(field)
    return result, fields


@pytest.mark.parametrize('part', ['1', '2'])
def test_blinken_subject_excludes_nomination_heading_and_part(engine, part):
    result, fields = extracted(engine, f'01 19 2021 Nominations -- Blinken Part {part}.pdf')
    assert [f['raw'] for f in fields['subject_token']] == ['Blinken']
    assert [f['raw'] for f in fields['label']] == ['Nominations']
    assert [f['raw'] for f in fields['part_number']] == [part]
    assert fields['date_token'][0]['candidates'] == ['2021-01-19']
    assert 'name_token' not in fields
    assert not {'witness_id', 'nominee_id', 'person_id'} & fields.keys()
    assert not result['valid']


@pytest.mark.parametrize('name,subject', [
    ('02 08 24 Nominations -- Rand, Welton, Lang.pdf', 'Rand, Welton, Lang'),
    ('01-15-25-nominations__rubiopdf', 'rubio'),
    ('01-19-2021-nominations__blinken-part-1pdf&download=1', 'blinken'),
    ('03 26 26 Nominations -- Dillon, Adewale-Sadik, Kim_60f9d174-8f7b-46d4-8811-7fea4b21fa3d.pdf',
     'Dillon, Adewale-Sadik, Kim'),
    ("07 26 2023 Nominations -- Hankins, O'Brien, Rayes, Bradley.pdf", "Hankins, O'Brien, Rayes, Bradley"),
    # Constructed controls: the subject need not be a person or personal name.
    ('Nomination — Advisory Board.pdf', 'Advisory Board'),
    ('Nominations -- A.pdf', 'A'),
])
def test_shared_layout_preserves_subjects_and_suffixes(engine, name, subject):
    _, fields = extracted(engine, name)
    assert [f['raw'] for f in fields['subject_token']] == [subject]
    if '_60f9d174' in name:
        assert fields['opaque_uuid'][0]['raw'] == '60f9d174-8f7b-46d4-8811-7fea4b21fa3d'
    if 'part-1' in name:
        assert fields['part_number'][0]['raw'] == '1'
        assert fields['query_text'][0]['raw'] == '&download=1'
    if '02 08 24' in name:
        assert fields['date_token'][0]['candidates'] == []  # Do not invent a century.


@pytest.mark.parametrize('name', [
    'Nominations reform -- staffing.pdf',
    'Statement on Nominations -- Blinken.pdf',
    'Transcript_Nominations.pdf',
    'Nominations -- .pdf',
    'HHRG-119-IF00-Wstate-Nominations--Blinken-20250318.pdf',
])
def test_unrelated_titles_and_structured_witness_slots_are_not_reinterpreted(engine, name):
    result, _ = extracted(engine, name)
    assert not any(m['rule'] == 'nomination-heading-subject' for m in result['observations'])
