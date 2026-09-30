"""Complete named dates win over their contained month-first fragments."""
import subprocess
import sys

import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in result['observations']:
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    for m in result['suppressed']:
        assert name[m['start']:m['end']] == m['raw']
        assert all(name[f['start']:f['end']] == f['raw'] for f in m['fields'])
    return result


def named_dates(result):
    return [{f['name']: f for f in m['fields']} for m in result['observations']
            if m['rule'] in {'named-month-date','day-named-month-date'}]


@pytest.mark.parametrize('name,day,month,year,raw', [
    ('2022 USSOCOM Posture - Clarke - SASC (5APR22) (FINAL).pdf', '5', 'APR', '22', '5APR22'),
    ('2023 SOLIC-USSOCOM Posture - Maier-Fenton - SASC (7Mar23) (FINAL)1.pdf', '7', 'Mar', '23', '7Mar23'),
    ('28563C4-1_HS_22JUN21_SECNAV_SASC_Posture_hearing_Final.pdf', '22', 'JUN', '21', '22JUN21'),
    ('Statement-5-Apr-22.pdf', '5', 'Apr', '22', '5-Apr-22'),
    ('Statement-5 April 22.pdf', '5', 'April', '22', '5 April 22'),
])
def test_complete_short_year_date_keeps_day_and_year_without_choosing_century(engine, name, day, month, year, raw):
    result = checked(engine, name)
    match, = named_dates(result)
    assert match['day_token']['raw'] == day
    assert match['month_token']['raw'] == month
    assert match['year_token']['raw'] == year
    assert match['date_token']['raw'] == raw
    assert not match['date_token']['candidates']
    assert 'century remains unspecified' in match['date_token']['note']
    alternatives = [s for s in result['suppressed'] if s['rule']=='named-month-date']
    assert alternatives and any(f['name']=='day_token' and f['raw']==year for s in alternatives for f in s['fields'])


@pytest.mark.parametrize('text,expected', [
    ('5April2022','2022-04-05'), ('29Feb2024','2024-02-29'),
    ('April-5-2022','2022-04-05'), ('February 29, 2024','2024-02-29'),
    ('31DEC1999','1999-12-31'), ('01 January 2000','2000-01-01'),
])
def test_both_date_orders_keep_full_year_calendar_readings(engine, text, expected):
    match, = named_dates(checked(engine, f'Smith-{text}.pdf'))
    assert match['date_token']['raw'] == text
    assert match['date_token']['candidates'] == [expected]


@pytest.mark.parametrize('text', ['32APR22', '31Feb22', '29Feb2023', 'February-31-2024'])
def test_invalid_complete_dates_are_flagged_instead_of_replaced_by_valid_fragments(engine, text):
    match, = named_dates(checked(engine, f'Smith-{text}.pdf'))
    assert match['date_token']['raw'] == text
    assert not match['date_token']['candidates']
    assert 'Invalid named calendar date' in match['date_token']['note']


@pytest.mark.parametrize('text', ['April22', 'April-22', 'February29'])
def test_actual_month_day_without_year_is_preserved(engine, text):
    match, = named_dates(checked(engine, f'Smith-{text}.pdf'))
    assert match['date_token']['raw'] == text
    assert 'year_token' not in match
    assert not match['date_token']['candidates']


def test_independent_named_dates_are_both_retained(engine):
    result = checked(engine, 'Hearing-5APR22-followup-7Mar2023.pdf')
    matches = named_dates(result)
    assert [m['date_token']['raw'] for m in matches] == ['5APR22','7Mar2023']


def test_real_two_date_filename_retains_printed_order(engine):
    name = 'USCG-ADM Fagan-Testimony--Great Lakes Operations--S.OFCCM-1MAR24 (Final_28FEB24).pdf'
    matches = named_dates(checked(engine, name))
    assert [m['date_token']['raw'] for m in matches] == ['1MAR24','28FEB24']


@pytest.mark.parametrize('name,expected', [
    ('10MAY22 SASC SIOP Hearing Statement FINAL.pdf','SASC SIOP Hearing Statement FINAL'),
    ('18APR23_CNO_SASC_USN_Posture-Hearing_FINAL for Hill.pdf','CNO_SASC_USN_Posture-Hearing_FINAL for Hill'),
    ('April-5-2022-Smith.pdf','Smith'),
    ('29Feb2023-Smith.pdf','Smith'),
    ('5APR22-sammypdf.pdf','sammy'),
    ('5APR22-tobias-tedtimony.pdf','tobias'),
])
def test_name_remainder_survives_recognizing_the_complete_leading_date(engine, name, expected):
    result = checked(engine, name)
    matches = [m for m in result['observations'] if m['rule']=='unmatched-named-date-remainder']
    assert len(matches) == 1
    parts = {f['name']:f for f in matches[0]['fields']}
    assert parts['name_token']['raw'] == expected
    assert 'fallback assumption' in parts['name_token']['note']
    assert not any(f['name']=='generic_identifier' for m in result['observations'] for f in m['fields'])


def test_explicit_document_subject_keeps_a_refined_remainder(engine):
    name = '21jul26_sac_supplemental_cjcs_caine_written_testimony.pdf'
    result = checked(engine, name)
    match, = [m for m in result['observations'] if m['rule']=='subject-named-date-remainder']
    part, = [f for f in match['fields'] if f['name']=='subject_token']
    assert part['raw']=='sac_supplemental_cjcs_caine'
    assert not any(f['name']=='generic_identifier' for m in result['observations'] for f in m['fields'])


def test_named_date_remainder_respects_zip_name_exclusion(engine):
    result = checked(engine, '5APR22-Smith.zip')
    assert not any(m['rule']=='unmatched-named-date-remainder' for m in result['observations'])


@pytest.mark.parametrize('name', ['April22-Smith-42.pdf', '5APR22-42-Smith.pdf'])
def test_name_remainder_reuses_existing_identifier_fallback(engine, name):
    result = checked(engine, name)
    match, = [m for m in result['observations'] if m['rule']=='unmatched-named-date-remainder']
    parts = {f['name']:f['raw'] for f in match['fields']}
    assert parts['name_token'] == 'Smith'
    assert parts['generic_identifier'] == '42'


def test_name_remainder_reuses_existing_trailing_date_fallback(engine):
    result = checked(engine, '5APR22-Smith-2024-02-29.pdf')
    match, = [m for m in result['observations'] if m['rule']=='unmatched-named-date-remainder']
    parts = {f['name']:f['raw'] for f in match['fields']}
    assert parts['name_token'] == 'Smith'
    assert parts['date_token'] == '2024-02-29'


@pytest.mark.parametrize('name', [
    '5CDC28B7-6DD7-42E5-9E8B-BDF9AC4FEB38.pdf',
    '8DEC41FC0F68FFBD33366C8FAE6AA46483606F86D6D2EAA06545FEDBC7D8299B.mitchell-testimony.pdf',
    'HHRG-119-IF00-Wstate-5APR22-20250318.pdf',
])
def test_identifier_and_assigned_name_protection_stays_ahead_of_date_search(engine, name):
    assert not named_dates(checked(engine, name))


def test_many_repeated_candidate_dates_are_bounded():
    subprocess.run([sys.executable,'-c',
        'from house_naming import Engine; Engine().extract(("5APR22_" * 1500) + ".pdf")'],
        check=True, capture_output=True, timeout=8)
