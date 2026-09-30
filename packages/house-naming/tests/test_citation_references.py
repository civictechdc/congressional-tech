"""Printed source citations and measure spellings observed in the inventory."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, filename):
    result = engine.extract(filename)
    assert all(result[k] == value for k, value in engine.parse(filename).items())
    assert ''.join(p['raw'] for p in result['pieces']) == filename
    for observation in (*result['observations'], *result['suppressed']):
        for field in observation['fields']:
            assert filename[field['start']:field['end']] == field['raw']
            assert observation['start'] <= field['start'] <= field['end'] <= observation['end']
    return result


def fields(result, name):
    return [f for m in result['observations'] for f in m['fields'] if f['name'] == name]


@pytest.mark.parametrize('filename,marker,congress,number,label', [
    ('S. Hrg. 115-693.pdf', 'S. Hrg', '115', '693', 'Senate hearing citation'),
    ('s-hrg-115-693pdf', 's-hrg', '115', '693', 'Senate hearing citation'),
    ('shrg119-016_transcriptpdf', 'shrg', '119', '016', 'Senate hearing citation'),
    ('H. Rept 118-275.pdf', 'H. Rept', '118', '275', 'House report citation'),
    ('HRPT-113-HRept113-125.pdf', 'HRept', '113', '125', 'House report citation'),
    ('S. Rept. 119-12.pdf', 'S. Rept', '119', '12', 'Senate report citation'),
])
def test_observed_and_constructed_citations_retain_source_components(engine, filename, marker, congress, number, label):
    result = checked(engine, filename)
    assert [f['raw'] for f in fields(result, 'citation_marker')] == [marker]
    assert fields(result, 'citation_marker')[0]['label'] == label
    assert [f['raw'] for f in fields(result, 'citation_congress')] == [congress]
    assert [f['raw'] for f in fields(result, 'citation_number')] == [number]
    assert not fields(result, 'publication_number')
    assert not fields(result, 'generic_identifier')


def test_actual_placeholder_report_retains_independent_bill_reference(engine):
    result = checked(engine, 'H. Rept. 118-XX (H.R. 3935).pdf')
    assert fields(result, 'citation_congress')[0]['raw'] == '118'
    assert fields(result, 'number_placeholder')[0]['raw'] == 'XX'
    assert not fields(result, 'citation_number')
    assert fields(result, 'measure_number')[0]['raw'] == '3935'
    assert fields(result, 'measure_token')[0]['code'] == 'hr'


def test_actual_hearing_reference_does_not_consume_transcript_date(engine):
    result = checked(engine, 's-hrg-118-126_transcript_3162023pdf')
    assert fields(result, 'citation_number')[0]['raw'] == '126'
    assert fields(result, 'date_token')[0]['candidates'] == ['2023-03-16']
    assert 'transcript' in [f['raw'] for f in fields(result, 'label')]
    assert 'pdf' in [f['raw'] for f in fields(result, 'ignored_suffix')]


def test_constructed_multiple_citations_remain_separate(engine):
    result = checked(engine, 'Compare S.Hrg.118-10 and S.Hrg.119-12.pdf')
    assert [f['raw'] for f in fields(result, 'citation_congress')] == ['118', '119']
    assert [f['raw'] for f in fields(result, 'citation_number')] == ['10', '12']


def test_constructed_date_shaped_citation_number_stays_a_citation(engine):
    result = checked(engine, 'S.Hrg.119-12345.pdf')
    assert fields(result, 'citation_number')[0]['raw'] == '12345'
    assert not fields(result, 'short_date_token')
    assert not fields(result, 'date_token')
    assert any(s['rule'] == 'short-date-unpadded' for s in result['suppressed'])


@pytest.mark.parametrize('filename', [
    'S.Hrg.119.pdf', 'S.Hrg.119-.pdf', 'XS.Hrg.119-12.pdf',
    'S.Hrg.119-12abc.pdf', 'S.Hrg.1119-12.pdf',
    'Brown Testimony - SENR Cmte Hrg 11-19-25.pdf',
    'CHRG-119shrg12345.pdf',
    'HHRG-119-IF00-Wstate-SHrg119-12-20250318.pdf',
])
def test_incomplete_citations_dates_and_structured_slots_do_not_acquire_citations(engine, filename):
    assert not fields(checked(engine, filename), 'citation_marker')


@pytest.mark.parametrize('filename,raw,code,number', [
    ('s-res-206-062519', 's-res', 'sres', '206'),
    ('S_Res_120_Managers_Preamble_Amendment.pdf', 'S_Res', 'sres', '120'),
    ('09-21-22_h._res._1298_as_amended_tally_sheet.pdf', 'h._res.', 'hres', '1298'),
    ('s-con-res-10-062519', 's-con-res', 'sconres', '10'),
    ('s-j-res-10-080421', 's-j-res', 'sjres', '10'),
    ('h-r-5430-united-states-mexico-canada-agreement-implementation-act-', 'h-r', 'hr', '5430'),
    ('Testimony H_Con_Res_42.pdf', 'H_Con_Res', 'hconres', '42'),
    ('Testimony H-J-Res-42.pdf', 'H-J-Res', 'hjres', '42'),
])
def test_observed_and_constructed_measure_separators_share_vocabulary(engine, filename, raw, code, number):
    result = checked(engine, filename)
    assert raw in [f['raw'] for f in fields(result, 'measure_token')]
    assert code in [f['code'] for f in fields(result, 'measure_token')]
    reference = next(f for f in fields(result, 'measure_number') if f['raw'] == number)
    assert not any(f['start'] < reference['end'] and f['end'] > reference['start']
                   for f in fields(result, 'generic_identifier'))


@pytest.mark.parametrize('filename', [
    'AS-res-206.pdf', 'house-resources-206.pdf', 'S-resolution-206.pdf',
    'S_responses_206.pdf', 'HHRG-119-IF00-Wstate-S-Res-206-20250318.pdf',
])
def test_measure_word_boundaries_and_structured_person_ids_remain_protected(engine, filename):
    assert not fields(checked(engine, filename), 'measure_number')
