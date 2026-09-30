"""Printed remarks labels are distinct from document content or speaker identity."""
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
        for f in match['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert match['start'] <= f['start'] <= f['end'] <= match['end']
    return result


def fields(result, name, rule=None):
    return [f for m in result['observations'] if rule is None or m['rule'] == rule
            for f in m['fields'] if f['name'] == name]


@pytest.mark.parametrize('name,label', [
    ('02-09-22 Grassley Opening Remarks at Senate Judiciary Hearing on Targeted Drone Strikes3.pdf', 'Opening Remarks'),
    ('AMD CEO Lisa Su Senate Commerce Committee Prepared Remarks May 2025.pdf', 'Prepared Remarks'),
    ('20240503 Written Remarks Senate Commerce CPPSDS SubComm FINAL.pdf', 'Written Remarks'),
    ('Informal oral remarks of Dr. Michael Ryan, Executive Director of the WHO Health Emergencies Programme .pdf', 'oral remarks'),
    ('02.10.22 CLEAN HYDROGEN HEARING SEN MANCHIN REMARKS.pdf', 'REMARKS'),
    ('Chairman Manchin Final remarks.pdf', 'remarks'),
    ('061620_-chairman-kennedy-opening-remarks&download=1', 'opening-remarks'),
    ('lee-opening-remarks.docx', 'opening-remarks'),
    ('Sfraga.Testimony.Remarks.pdf', 'Remarks'),
    ('Smith Closing_Remarks.pdf', 'Closing_Remarks'),
    ('Smith Remarks.pdf', 'Remarks'),
    ('Smith Opening-Remarkspdf.pdf', 'Opening-Remarks'),
])
def test_source_labels_without_official_type_or_person_meanings(engine, name, label):
    result = checked(engine, name)
    field, = fields(result, 'label', 'remarks-wording')
    assert field['raw'] == label
    assert field['code'] is None and field['context'] is None
    assert not fields(result, 'author') and not fields(result, 'person_id')


@pytest.mark.parametrize('name,qualifiers', [
    ('9.12 Opening Remarks Final Final.pdf', ['Final', 'Final']),
    ('2020.8.5_Simons oral remarks final.pdf', ['final']),
    ('Chairman Manchin Final remarks.pdf', ['Final']),
    ('Dr. Kirkpatrick Oral Remarks - SASC ETC Open Hearing 4.19.23 FINAL.pdf', ['FINAL']),
    ('20240503 Written Remarks Senate Commerce CPPSDS SubComm FINAL.pdf', ['FINAL']),
    ('Prepared Remarks Public Health Hearing.pdf', []),
    ('Final Remarks Public Health Hearing.pdf', ['Final']),
    ('Public Health Opening Remarks.pdf', []),
    ('Final Program Opening Remarks.pdf', []),
    ('Opening Remarks on Final Program.pdf', []),
])
def test_reused_contextual_qualifiers(engine, name, qualifiers):
    assert [f['raw'] for f in fields(checked(engine, name), 'qualifier_wording')] == qualifiers


def test_dates_and_opaque_prefixes_remain_distinct(engine):
    name = '064CEC2BE43712225235DF39F1D57BA2BF2E6C10412E3C7BC2DB0F610CFE132A.06.10.2026-opening-remarks.pdf'
    result = checked(engine, name)
    assert [f['raw'] for f in fields(result, 'label', 'remarks-wording')] == ['opening-remarks']
    assert [f['raw'] for f in fields(result, 'opaque_identifier')] == [name[:64]]
    assert [f['raw'] for f in fields(result, 'date_token')] == ['06.10.2026']


def test_other_labels_and_month_precision_remain(engine):
    result = checked(engine, 'Sfraga.Testimony.Remarks.pdf')
    assert {f['raw'] for f in fields(result, 'label')} == {'Testimony', 'Remarks'}
    result = checked(engine, 'AMD CEO Lisa Su Senate Commerce Committee Prepared Remarks May 2025.pdf')
    assert fields(result, 'month_year_token')[0]['candidates'] == ['2025-05']


@pytest.mark.parametrize('name', [
    'Remarks20250318.pdf', 'Opening Remarks20250318.pdf',
])
def test_date_shaped_suffix_is_not_a_local_number(engine, name):
    result = checked(engine, name)
    assert fields(result, 'label', 'remarks-wording')
    assert not fields(result, 'local_number_token')
    assert any(f['raw'] == '20250318' for f in fields(result, 'date_token'))


def test_literal_attached_numbers_use_existing_role(engine):
    result = checked(engine, 'Opening Remarks3_Final2.pdf')
    assert [f['raw'] for f in fields(result, 'local_number_token')] == ['3', '2']
    assert all('not an established bill or amendment sequence' in f['note']
               for f in fields(result, 'local_number_token'))


@pytest.mark.parametrize('name', [
    'Remarksman.pdf', 'Remarksmith.pdf', 'PreRemarks.pdf',
    'HHRG-119-IF00-Wstate-Opening-Remarks-20250318.pdf',
    'HHRG-119-IF00-Wstate-Remarks-20250318.pdf',
])
def test_embedded_words_and_structured_witness_slots(engine, name):
    assert not fields(checked(engine, name), 'label', 'remarks-wording')
