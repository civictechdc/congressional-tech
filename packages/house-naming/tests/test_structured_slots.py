"""Explicit source slots remain visible before broad token scans."""
import subprocess
import sys

import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def fields(result, name):
    return [f for m in result['observations'] for f in m['fields'] if f['name'] == name]


def checked(engine, filename):
    result = engine.extract(filename)
    assert all(result[k] == v for k, v in engine.parse(filename).items())
    assert ''.join(p['raw'] for p in result['pieces']) == filename
    for match in result['observations']:
        for field in match['fields']:
            assert filename[field['start']:field['end']] == field['raw']
    return result


@pytest.mark.parametrize('subject,amendment', [
    ('5308','14'), ('5308','15'), ('HR2474','17'), ('HR4334','9'),
    ('HR4674','51'), ('HR4674','52'), ('HR8294','5'),
])
def test_real_malformed_sponsor_slot_is_preserved_without_repair(engine, subject, amendment):
    filename = f'BILLS-116-{subject}-KOOO395-Amdt-{amendment}.pdf'
    result = checked(engine, filename)
    assert [f['raw'] for f in fields(result, 'sponsor_identifier_token')] == ['KOOO395']
    assert not fields(result, 'bioguide_token')
    assert all(f['raw'] != 'K000395' for m in result['observations'] for f in m['fields'])
    matches = [m for m in result['observations'] if m['rule'] == 'unverified-sponsor-amendment']
    assert len(matches) == 1
    actual = {f['name']:f['raw'] for f in matches[0]['fields']}
    assert actual['subject_token'] == subject and actual['amendment_token'] == amendment
    if subject.startswith('HR'):
        assert fields(result, 'measure_number')[0]['raw'] == subject[2:]
    else:
        assert not fields(result, 'measure_number')  # Do not invent a bill type.


def test_valid_sponsor_shape_does_not_gain_a_malformed_interpretation(engine):
    result = checked(engine, 'BILLS-116-HR8294-K000395-Amdt-5.pdf')
    assert [f['raw'] for f in fields(result, 'bioguide_token')] == ['K000395']
    assert not fields(result, 'sponsor_identifier_token')
    assert sum(m['rule'] == 'sponsored-amendment' for m in result['observations']) == 1


@pytest.mark.parametrize('slot,separator', [('000123','-'), ('B000123',' ')])
def test_explicit_malformed_sponsor_slot_does_not_become_a_date(engine, slot, separator):
    result = checked(engine, f'BILLS-119-HR12-{slot}{separator}Amdt-1.pdf')
    assert fields(result, 'sponsor_identifier_token')[0]['raw'] == slot
    assert not fields(result, 'short_date_token') and not fields(result, 'date_token')
    # The rejected generic interpretation stays inspectable.
    assert any(s['rule'] == 'short-date-compact' for s in result['suppressed'])


def test_specific_slot_keeps_amendment_groups_and_updates(engine):
    result = checked(engine, 'BILLS-119-HR12-KOOO395-Amdt-1A-Enbloc-2-U1.pdf')
    assert fields(result, 'sponsor_identifier_token')[0]['raw'] == 'KOOO395'
    assert fields(result, 'amendment_identifier')[0]['raw'] == '1A'
    assert fields(result, 'enbloc_number')[0]['raw'] == '2'
    assert fields(result, 'revision_number')[0]['raw'] == '1'


@pytest.mark.parametrize('filename', [
    'BILLS-115-HR6470-FC-AP-FY2019-AP00-Amdt-1.pdf',
    'BILLS-116--AP--AP00-FY2020EW_Bill.pdf',
    'KOOO395-Amdt-1.pdf',
    'BILLS-119HR12-KOOO395-Appendix-1.pdf',
])
def test_other_routing_and_prose_do_not_establish_sponsor_roles(engine, filename):
    result = checked(engine, filename)
    assert not fields(result, 'sponsor_identifier_token')
    assert not fields(result, 'bioguide_token')


def test_date_after_amendment_slot_remains_source_text_not_event_date(engine):
    result = checked(engine, 'BILLS-119-HR12-KOOO395-Amdt-20240123.pdf')
    assert fields(result, 'amendment_token')[0]['raw'] == '20240123'
    assert not fields(result, 'date_token') and not fields(result, 'short_date_token')


def test_numeric_date_without_explicit_sponsor_slot_is_still_a_candidate(engine):
    result = checked(engine, 'Smith-000123.pdf')
    assert fields(result, 'date_token') or fields(result, 'short_date_token')
    assert not fields(result, 'sponsor_identifier_token')


@pytest.mark.parametrize('measure', ['HR','S','HRes','SRes','HJRes','SJRes','HConRes','SConRes'])
@pytest.mark.parametrize('placeholder', ['', '__', 'XX'])
def test_unnumbered_subject_keeps_type_and_placeholder_without_a_number(engine, measure, placeholder):
    filename = f'BILLS-119-{measure}{placeholder}-C001036-Amdt-2.pdf'
    result = checked(engine, filename)
    typed = fields(result, 'measure_token')
    assert len(typed) == 1 and typed[0]['raw'] == measure and typed[0]['code'] == measure.lower()
    assert not fields(result, 'measure_number')
    assert [f['raw'] for f in fields(result, 'number_placeholder')] == ([placeholder] if placeholder else [])


@pytest.mark.parametrize('subject', ['HResource', 'HRTitle', 'SAMPLE', 'NA', 'CP', 'XX', '000', '1234'])
def test_subject_words_and_untyped_numbers_do_not_invent_a_measure_type(engine, subject):
    result = checked(engine, f'BILLS-119-{subject}-C001036-Amdt-2.pdf')
    assert not fields(result, 'measure_token') and not fields(result, 'measure_number')
    assert not fields(result, 'number_placeholder')


@pytest.mark.parametrize('amendment,identifier', [
    ('15-U15','15'), ('001-U1','001'), ('1A-U1','1A'),
    ('1A2-U1','1A2'), ('1DD','1DD'), ('2-Enbloc-3','2'),
])
def test_amendment_identifier_is_separate_from_update_and_group_numbers(engine, amendment, identifier):
    result = checked(engine, f'BILLS-119-HR12-A000055-Amdt-{amendment}.pdf')
    assert fields(result, 'amendment_token')[0]['raw'] == amendment
    assert {f['raw'] for f in fields(result, 'amendment_identifier')} == {identifier}
    assert all(f['name'] != 'measure_number' or f['raw'] == '12'
               for m in result['observations'] for f in m['fields'])


def test_local_amendment_spelling_remains_unsplit_without_supported_structure(engine):
    result = checked(engine, 'BILLS-119-HR12-A000055-Amdt-SCHAKO_047.pdf')
    assert fields(result, 'amendment_token')[0]['raw'] == 'SCHAKO_047'
    assert not fields(result, 'amendment_identifier')


@pytest.mark.parametrize('amendment', ['2', '000', '1068_01_xml',
    '5555-FC-AINS_01XMLfiledbyRepMiller-MeekstoHR5555', '033_ANS', '15-U0'])
def test_numeric_ids_and_local_codes_do_not_gain_partial_or_duplicate_identifiers(engine, amendment):
    result = checked(engine, f'BILLS-119-HR12-A000055-Amdt-{amendment}.pdf')
    assert fields(result, 'amendment_token')[0]['raw'] == amendment
    assert not fields(result, 'amendment_identifier')


def test_complex_enbloc_name_does_not_turn_its_first_number_into_an_amendment_id(engine):
    filename = 'BILLS-115-502-G000577-Amdt-4-141619and20-Enbloc-4-141619and20.pdf'
    result = checked(engine, filename)
    assert not any(f['raw'] == '4' for f in fields(result, 'amendment_identifier'))


def test_explicit_underscores_separate_a_subject_title_from_a_missing_number(engine):
    result = checked(engine, 'BILLS-118-HR____AmericanPrivacyRightsActdiscussiondraft-C001036-Amdt-2.pdf')
    assert fields(result, 'measure_token')[0]['code'] == 'hr'
    assert fields(result, 'number_placeholder')[0]['raw'] == '____'
    assert fields(result, 'descriptor')[0]['raw'] == 'AmericanPrivacyRightsActdiscussiondraft'
    assert not fields(result, 'measure_number')


def test_long_malformed_amendment_identifier_does_not_backtrack_over_digit_partitions():
    code = '''
from house_naming import Engine
name = 'BILLS-119-HR12-A000055-Amdt-' + '9' * 12000 + '@.pdf'
result = Engine().extract(name)
assert not any(f['name'] == 'amendment_identifier' for m in result['observations'] for f in m['fields'])
assert any(f['name'] == 'amendment_token' and f['raw'] == '9' * 12000 + '@' for m in result['observations'] for f in m['fields'])
'''
    subprocess.run([sys.executable, '-c', code], check=True, timeout=5)
