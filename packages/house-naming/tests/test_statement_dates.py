"""Actual corpus cases plus constructed boundary and calendar controls."""
import subprocess
import sys

import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def extract(engine, name):
    result = engine.extract(name)
    assert all(result[k] == v for k, v in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for observation in (*result['observations'], *result['suppressed']):
        for field in observation['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert observation['start'] <= field['start'] <= field['end'] <= observation['end']
    return result


def dates(result):
    return [{f['name']: f for f in m['fields']} for m in result['observations']
            if m['rule'] in {'named-month-date', 'day-named-month-date'}]


def labels(result):
    return [f for m in result['observations']
            if m['rule'] in {'statement-abbreviation', 'dated-statement-suffix'}
            for f in m['fields'] if f['name'] == 'label']


@pytest.mark.parametrize('name,label,number', [
    ('05JUN2019GraySMNT.pdf', 'SMNT', None),
    ('02JUN2020.GAO.STMNT.pdf', 'STMNT', None),
    ('18JUN2020CASSIDYSTMNT1.pdf', 'STMNT', '1'),
    ('29JUL2020Glauber~IFPRISTMNT3.pdf', 'STMNT', '3'),
    ('BEGICH stmt.docx', 'stmt', None),
    ('Afghanistan Opening Stmt_Austin.Milley.McKenzie.9.28.v61.pdf', 'Opening Stmt', None),
    ('CEG-Opening-Stmt-July-12-Money-Laundering-FINAL-1.docx', 'Opening-Stmt', None),
    ('Global Security Hearing Stmt_02.15.23_final1.pdf', 'Stmt', None),
    ('World Wide Threats Opening Stmt_05.10.22_final.pdf', 'Opening Stmt', None),
    ('05JUN2019 Opening STMNT.pdf', 'Opening STMNT', None),
])
def test_corpus_statement_abbreviations_are_literal_labels(engine, name, label, number):
    result = extract(engine, name)
    field, = labels(result)
    assert field['raw'] == label
    assert not field['code'] and not field['context'] and not field['label']
    assert not field['candidates']
    nums = [f['raw'] for m in result['observations'] if m['rule']=='dated-statement-suffix'
            for f in m['fields'] if f['name']=='local_number_token']
    assert nums == ([] if number is None else [number])


@pytest.mark.parametrize('name', [
    'assessment.pdf', 'assessmnt.pdf', 'ASSESSMNT.pdf', 'statementary.pdf',
    'GraySMNT.pdf', '05JUN2019GraySmnt.pdf', '05JUN2019GraySMNTdraft.pdf',
    'HHRG-119-IF00-Wstate-BEGICHStmt-20250318.pdf',
    'HHRG-119-IF00-Wstate-05JUN2019GraySMNT-20250318.pdf',
])
def test_constructed_unbounded_or_assigned_tokens_do_not_become_statement_labels(engine, name):
    assert not labels(extract(engine, name))


@pytest.mark.parametrize('name,raw,day,month', [
    ('10 Jun SASC CJCS Statement (GEN Milley).pdf', '10 Jun', '10', 'Jun'),
    ('12May SSP Written Testimony to SASC-Strategic Forces Hearing Nuclear Forces.pdf', '12May', '12', 'May'),
    ('17 Jun SAC Statement (GEN Milley)2.pdf', '17 Jun', '17', 'Jun'),
    ('2022 AFSOC Posture Statement (27 April) (Final).pdf', '27 April', '27', 'April'),
    ('CJCS MFR Ref 8 Jan Phone Call w Speaker Pelosi.pdf', '8 Jan', '8', 'Jan'),
    ('DAF Written Statement - SASC Recruiting & Retention (22 Mar).pdf', '22 Mar', '22', 'Mar'),
    ('Papa Ola Lokahi - 1 June SCIA Field Hearing Testimony_Dr. Daniels.pdf', '1 June', '1', 'June'),
    ('LTG Mingus opening remarks_26 OCT_Final.pdf', '26 OCT', '26', 'OCT'),
    ('Written Statement for SecDef to SACD_OMB cleared_11May.pdf', '11May', '11', 'May'),
])
def test_yearless_corpus_dates_preserve_only_printed_components(engine, name, raw, day, month):
    match, = dates(extract(engine, name))
    assert match['date_token']['raw'] == raw
    assert match['day_token']['raw'] == day
    assert match['month_token']['raw'] == month
    assert 'year_token' not in match
    assert not match['date_token']['candidates']
    assert 'year or century remains unspecified' in match['date_token']['note']


def test_corpus_complete_and_yearless_dates_keep_their_order(engine):
    result = extract(engine, '18APR23_SECNAV Posture Statement_SASC_Final_Updated 13 APR.PDF')
    found = dates(result)
    assert [d['date_token']['raw'] for d in found] == ['18APR23', '13 APR']
    assert found[0]['year_token']['raw'] == '23'
    assert 'year_token' not in found[1]


@pytest.mark.parametrize('name,raw,remainder', [
    ('16DEC202BATEMANSTMNT.pdf', '16DEC202', 'BATEMANSTMNT'),
    ('16DEC202DOKHOLYANSTMNT.pdf', '16DEC202', 'DOKHOLYANSTMNT'),
    ('21JUL202MarshallSTMNT.pdf', '21JUL202', 'MarshallSTMNT'),
    ('December 16 202-Smith.pdf', 'December 16 202', 'Smith'),
])
def test_malformed_years_retain_spelling_without_repair(engine, name, raw, remainder):
    result = extract(engine, name)
    match, = dates(result)
    assert match['date_token']['raw'] == raw
    assert match['year_token']['raw'] == '202'
    assert not match['date_token']['candidates']
    assert 'Unsupported printed year width' in match['date_token']['note']
    assert any(f['name']=='name_token' and f['raw']==remainder
               for m in result['observations'] for f in m['fields'])
    assert not any(f['name']=='generic_identifier' for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('text,valid', [
    ('29 Feb', True), ('29Feb2024', True), ('29Feb2023', False),
    ('31 APR', False), ('00 June', False), ('32 July', False),
])
def test_constructed_yearless_and_complete_calendar_controls(engine, text, valid):
    match, = dates(extract(engine, f'Smith-{text}.pdf'))
    assert ('Invalid named calendar date' not in match['date_token']['note']) == valid


@pytest.mark.parametrize('name', [
    '12Mayfield.pdf', '13APRIL20222.pdf', '16DEC20202.pdf',
    '6039D215-30BB-4DEC-8F2E-39E8A7B0ABB3.pdf',
    '6E52F306-3FEB-4D13-AD10-9BEE4C0F3F43.pdf',
    'C143E129-AB64-40CA-8DEC-4BC6098F1C83.pdf',
    'HHRG-119-IF00-Wstate-13APR-20250318.pdf',
])
def test_constructed_partial_words_years_and_identifiers_are_not_yearless_dates(engine, name):
    assert not dates(extract(engine, name))


@pytest.mark.parametrize('name,month_first', [('16DEC2.pdf', 'DEC2'), ('16 DEC 2.pdf', 'DEC 2')])
def test_existing_month_day_alternative_is_not_replaced_by_truncated_day_month(engine, name, month_first):
    # A single trailing digit is still a possible day in the existing month-first
    # interpretation; it must not be silently dropped to manufacture a new date.
    match, = dates(extract(engine, name))
    assert match['date_token']['raw'] == month_first
    assert 'year_token' not in match


@pytest.mark.parametrize('name,raw', [
    ('Dr. Adesina. US.Senate Appropriations Subcommittee Testimony. FINAL.May 9_ 7.15 am.pdf', 'May 9'),
    ('Edelman-Miller Opening Statement SASC Hearing Sept. 20 20225.pdf', 'Sept. 20'),
    ('results-of-the-open-executive-session-june-9-102021', 'june-9'),
    ('December 16 20222.pdf', 'December 16'),
])
def test_month_day_readings_survive_unsupported_following_number_text(engine, name, raw):
    match, = dates(extract(engine, name))
    assert match['date_token']['raw'] == raw
    assert 'year_token' not in match
    assert not match['date_token']['candidates']


@pytest.mark.parametrize('name', [
    'Written%20Testimony%20Feb%204.pdf', 'Statement%20May.pdf',
    'Hearing%31APR.pdf', '20Feb2024.pdf',
])
def test_percent_encoded_bytes_cannot_be_a_new_day_token(engine, name):
    found = dates(extract(engine, name))
    if name == '20Feb2024.pdf':
        assert [m['date_token']['raw'] for m in found] == ['20Feb2024']
    else:
        assert not found


def test_long_statement_and_date_controls_are_bounded():
    subprocess.run([sys.executable, '-c',
        'from house_naming import Engine; e=Engine(); '
        'e.extract("05JUN2019" + "A" * 15000 + "SMNT.pdf"); '
        'e.extract("13 APR_" * 1400 + ".pdf")'],
        check=True, capture_output=True, timeout=8)
