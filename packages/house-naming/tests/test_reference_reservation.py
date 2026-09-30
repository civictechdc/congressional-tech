"""Explicit numeric references own their digits before generic date scans."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('reference,field,number', [
    ('HR111111', 'measure_number', '111111'),
    ('H.R. 12345', 'measure_number', '12345'),
    ('S.Res.20250318', 'measure_number', '20250318'),
    ('Amendment111111', 'amendment_token', '111111'),
    ('Amdt-12345', 'amendment_token', '12345'),
    ('Exhibit 12345', 'item_token', '12345'),
    ('Agenda Item 111111', 'item_token', '111111'),
    ('Attachment 20250318', 'item_token', '20250318'),
    ('x-SD111111', 'document_identifier', '111111'),
    ('x-QFR12345', 'document_identifier', '12345'),
    ('x-Vote20250318', 'document_identifier', '20250318'),
    ('S.Hrg.119-12345', 'citation_number', '12345'),
])
@pytest.mark.parametrize('suffix', ['', ' Hearing-2025-03-19'])
def test_reference_wins_without_hiding_adjacent_date(engine, reference, field, number, suffix):
    name = reference + suffix + '.pdf'
    result = engine.extract(name)
    fields = [f for m in result['observations'] for f in m['fields']]
    identifier = next(f for f in fields if f['name'] == field and f['raw'] == number)
    dates = [f for f in fields if f['name'] in {'date_token', 'short_date_token'}]
    assert not any(f['start'] < identifier['end'] and f['end'] > identifier['start'] for f in dates)
    assert bool(dates) == bool(suffix)
    if suffix:
        assert any(f['candidates'] == ['2025-03-19'] for f in dates)
    assert any(s['start'] < identifier['end'] and s['end'] > identifier['start']
               and s['reason'] == 'Overlaps a structured or already assigned token.'
               for s in result['suppressed'])
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in (*result['observations'], *result['suppressed']):
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']


@pytest.mark.parametrize('subject', ['HR111111', 'Amdt111111', 'SD111111', 'Exhibit12345'])
def test_structured_witness_identifier_remains_opaque(engine, subject):
    result = engine.extract(f'HHRG-119-IF00-Wstate-{subject}-20250318.pdf')
    assert not any(m['rule'] in {'measure-reference', 'amendment-reference', 'exhibit-reference', 'document-suffix'}
                   for m in result['observations'])


def test_reference_and_complete_uuid_remain_independent(engine):
    result = engine.extract('HR111111-11111111-1111-4111-8111-111111111111.pdf')
    fields = [f for m in result['observations'] for f in m['fields']]
    assert any(f['name'] == 'measure_number' and f['raw'] == '111111' for f in fields)
    assert any(f['name'] == 'opaque_uuid' for f in fields)
    assert not any(f['name'] in {'date_token', 'short_date_token'} for f in fields)


@pytest.mark.parametrize('name,raw', [
    ('Burman Statement - Attachment 3-27-19 SENR Cmte WP Subcmte Hrg.pdf', '3-27-19'),
    ('Cecere Testimony Attachment 9-22-22.pdf', '9-22-22'),
    ('Attachment 06.12.2019.pdf', '06.12.2019'),
    ('Hershman_APQ s_10-29-19.pdf', '10-29-19'),
])
def test_reference_cannot_cut_a_complete_separated_date(engine, name, raw):
    result = engine.extract(name)
    assert any(f['name'] == 'date_token' and f['raw'] == raw
               for m in result['observations'] for f in m['fields'])
    assert any(s['reason'] == 'Reference would consume only a prefix of a complete separated date.'
               for s in result['suppressed'])
