"""Keep complete malformed date shapes without repairing source digits."""
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


@pytest.mark.parametrize('name,raw', [
    ('Transcript_03.01.20231.pdf', '03.01.20231'),
    ('20-11_03-04-20201.pdf', '03-04-20201'),
    ('19-13_02-14-191.pdf', '02-14-191'),
    ('George Testimony Addendum 9-25-191.pdf', '9-25-191'),
    ('Clayton Testimony 11-17-202.pdf', '11-17-202'),
    ('SCA_Dole_6_14_171.pdf', '6_14_171'),
    ('Official Hearing Transcript_10.22.20254.pdf', '10.22.20254'),
    ('Testimony - Alur - 2022-09-141.pdf', '2022-09-141'),
    ('EBM Results - 2022-11-175.pdf', '2022-11-175'),
    ('JFR Afghanistan outside witnesses hearing 2021.09.291.pdf', '2021.09.291'),
    ('JFR opening statement Afghanistan.South.Central Asia hearing 2021.10.252.pdf', '2021.10.252'),
    ('Statement for Record-Final Emergency Interim Report-2019-04-161.pdf', '2019-04-161'),
    ('Statement for Record-Final Emergency Interim Report-2019-04-162.pdf', '2019-04-162'),
    ('Statement for Record-Final Emergency Interim Report-2019-04-163.pdf', '2019-04-163'),
    ('Statement for Record-Final Emergency Interim Report-2019-04-164.pdf', '2019-04-164'),
    ('Smith 02-30-20231.pdf', '02-30-20231'),
    ('Smith 31-12-20231 final.pdf', '31-12-20231'),
])
def test_actual_and_constructed_complete_shapes_have_no_repaired_date(engine, name, raw):
    result = checked(engine, name)
    field, = [f for m in result['observations'] for f in m['fields']
              if f['name'] == 'date_token' and f['raw'] == raw]
    assert field['name'] == 'date_token' and field['raw'] == raw
    assert not field['candidates']
    assert 'unsupported numeric component length' in field['note']
    assert 'not repaired' in field['note']
    for m in result['observations']:
        for other in m['fields']:
            if other is field:
                continue
            if other['name'] in {'generic_identifier', 'date_token', 'short_date_token'}:
                assert not (other['start'] < field['end'] and other['end'] > field['start'])


def test_old_fragment_reading_remains_inspectable(engine):
    result = checked(engine, 'Transcript_03.01.20231.pdf')
    assert any(f['raw'] == '20231' and f['name'] == 'short_date_token'
               for m in result['suppressed'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    'Smith 2024-02-29.pdf', 'Smith 02-29-2024.pdf', 'Smith 2-29-24.pdf',
    'Smith 13-14-20231.pdf', 'Smith 00-12-20231.pdf', 'Smith 12-32-20231.pdf',
    'Smith 112-3-20231.pdf', 'Smith 2-3-202311.pdf',
    'Smith 2024-13-291.pdf',
    'BILLS-119-HR123-4-20231.pdf',
    'BILLS-119-HR2-3-20231.pdf',
    'HHRG-119-IF00-Wstate-Smith2-3-20231-20250318.pdf',
    'S.Hrg.119-12345.pdf',
])
def test_valid_dates_and_assigned_identifiers_are_not_malformed_shapes(engine, name):
    result = checked(engine, name)
    assert not any(m['rule'] == 'malformed-numeric-date' for m in result['observations'])


def test_independent_valid_date_and_malformed_date_both_survive(engine):
    result = checked(engine, 'Smith 02-29-2024 updated 03.01.20231.pdf')
    dates = {f['raw']: f['candidates'] for m in result['observations'] for f in m['fields']
             if f['name'] == 'date_token'}
    assert dates['02-29-2024'] == ['2024-02-29']
    assert dates['03.01.20231'] == []


def test_partial_labeled_date_remains_a_suppressed_alternative(engine):
    result = checked(engine, 'Official Hearing Transcript_10.22.20254.pdf')
    old, = [m for m in result['suppressed'] if m['rule'] == 'labeled-date']
    assert any(f['name'] == 'date_token' and f['raw'] == '10.22.2025'
               and f['candidates'] == ['2025-10-22'] for f in old['fields'])
    assert any(f['name'] == 'label' and f['raw'] == 'Official Hearing Transcript'
               for m in result['observations'] for f in m['fields'])


def test_partial_year_first_date_keeps_the_explicit_subject(engine):
    result = checked(engine, 'Testimony - Alur - 2022-09-141.pdf')
    assert any(f['name'] == 'subject_token' and f['raw'] == 'Alur'
               for m in result['observations'] for f in m['fields'])
    old, = [m for m in result['suppressed'] if m['rule'] == 'labeled-subject-date']
    assert any(f['name'] == 'date_token' and f['raw'] == '2022-09-14'
               and f['candidates'] == ['2022-09-14'] for f in old['fields'])


@pytest.mark.parametrize('name,code', [('S-Res-2-3-20231.pdf', 'sres'), ('S 2-3-20231.pdf', 's')])
def test_explicit_measure_number_is_not_consumed_by_malformed_date(engine, name, code):
    result = checked(engine, name)
    assert any(f['name'] == 'measure_token' and f['code'] == code
               for m in result['observations'] for f in m['fields'])
    assert any(f['name'] == 'measure_number' and f['raw'] == '2'
               for m in result['observations'] for f in m['fields'])
    assert not any(m['rule'] == 'malformed-numeric-date' for m in result['observations'])


@pytest.mark.parametrize('name,identifiers', [
    ('Poster and Handout_R&E Ligado Hearing MDG Final 1235_05-06-291.pptx', ['1235']),
    ('Testimony Smith_1235_05-06-291.pdf', ['1235']),
    ('05-06-291_1235_Smith_2.pdf', ['1235', '2']),
    ('05-06-291_1235_Smith_2_03-04-20231.pdf', ['1235', '2']),
])
def test_complete_date_shapes_preserve_independent_remainder_identifiers(engine, name, identifiers):
    result = checked(engine, name)
    found = sorted({(f['start'], f['raw']) for m in result['observations'] for f in m['fields']
                    if f['name'] == 'generic_identifier'})
    assert [raw for _, raw in found] == identifiers
