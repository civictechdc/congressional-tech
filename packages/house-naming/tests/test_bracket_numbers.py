"""Trailing bracket syntax retains digits without inventing their role."""
import pytest

from house_naming import Engine
from house_naming.filenames import parse_filename


@pytest.fixture(scope='module')
def engine():
    return Engine()


def bracket_numbers(engine, name):
    result = engine.extract(name)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    assert parse_filename(name).model_dump(mode='json')['matches'] == result['observations']
    fields = [f for m in result['observations'] if m['rule'] == 'bracketed-terminal-number'
              for f in m['fields']]
    for field in fields:
        assert name[field['start']:field['end']] == field['raw']
        assert field['name'] == 'local_number_token'
        assert field['code'] is None and field['candidates'] == []
        assert 'no copy, revision' in field['note']
    return fields


@pytest.mark.parametrize('name,number', [
    # Retained source names spanning several existing layouts.
    ('CHRG-113shrg91664(1).pdf', '1'),
    ('Prepared Statement-Boyd-2022-03-10 (1).pdf', '1'),
    ('Witness List 3-10-22 SENR Cmte Hrg[1].pdf', '1'),
    ('ABC Testimony (00303050).pdf', '00303050'),
    ('04.26 DIB experts JMI OPENING (002).pdf', '002'),
    ('Hruby APQs[3].pdf', '3'),
    ('FINAL DOI Tahsuda Testimony re S.1211 (1).docx.pdf', '1'),
    # Constructed syntax/transport controls; no role inferred from these numbers.
    (' Testimony [0002].pdf ', '0002'),
    ('Testimony(0).pdf', '0'),
    ('Testimony [1]', '1'),
    ('(1).pdf', '1'),
    ('Testimony (2).xml.htm', '2'),
    ('Testimony(2).pdf?download=1', '2'),
    ('Testimony(2).pdf&download=1', '2'),
])
def test_reads_literal_bracketed_number(engine, name, number):
    field, = bracket_numbers(engine, name)
    assert field['raw'] == number


@pytest.mark.parametrize('name', [
    'Testimony (1].pdf', 'Testimony [1).pdf',
    'Testimony [1.pdf', 'Testimony 1].pdf',
    'Testimony(1) appendix.pdf', 'Testimony[1]-final.pdf',
    'Testimony(1A).pdf', 'Testimony(1.2).pdf',
    'Testimony(1-2).pdf', 'Testimony().pdf', 'Testimony[].pdf',
    'Testimony1.pdf', 'Testimony 1.pdf', 'Testimony(１２).pdf',
    'download.pdf?name=Testimony(1)',
    'HHRG-119-IF00-Wstate-Smith(1)-20260101.pdf',
    'BILLS-119-HR1-A000001-Amdt-AMD(1).pdf',
])
def test_requires_terminal_matched_brackets_and_unclaimed_digits(engine, name):
    assert not bracket_numbers(engine, name)


@pytest.mark.parametrize('name,date_field,raw', [
    ('MAUREEN RIORDAN Resume (62621).pdf', 'short_date_token', '62621'),
    ('Testimony (20260101).pdf', 'date_token', '20260101'),
    ('Testimony [010126].pdf', 'short_date_token', '010126'),
])
def test_existing_calendar_reading_keeps_precedence(engine, name, date_field, raw):
    assert not bracket_numbers(engine, name)
    assert any(f['name'] == date_field and f['raw'] == raw
               for m in engine.extract(name)['observations'] for f in m['fields'])


def test_invalid_date_candidate_is_retained_without_repair(engine):
    name = 'ABC Testimony (00303050).pdf'
    field, = bracket_numbers(engine, name)
    assert field['raw'] == '00303050'
    assert any(f['name'] == 'date_token' and f['raw'] == '00303050'
               for m in engine.extract(name)['suppressed'] for f in m['fields'])


def test_publication_and_local_numbers_remain_distinct(engine):
    name = 'CHRG-113shrg91664(1).pdf'
    assert bracket_numbers(engine, name)[0]['raw'] == '1'
    fields = [f for m in engine.extract(name)['observations'] for f in m['fields']]
    assert next(f['raw'] for f in fields if f['name'] == 'publication_number') == '91664'
    assert not any(f['name'] in {'part_number', 'revision_number', 'copy_number'} for f in fields)
