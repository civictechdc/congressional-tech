"""Observed document wording plus explicit boundary and preservation controls."""
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
    for m in (*result['observations'], *result['suppressed']):
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result


def fields(result, kind):
    return [f for m in result['observations'] for f in m['fields'] if f['name']==kind]


@pytest.mark.parametrize('name,label,subject', [
    ('-fernandez-resp-to-qfrs', 'resp-to-qfrs', '-fernandez'),
    ('Bhatia Responses to QFRs.pdf', 'Responses to QFRs', 'Bhatia'),
    ('Dimke Responses to Written Questions for the Record.pdf', 'Responses to Written Questions for the Record', 'Dimke'),
    ('Beckering Responses to Questions for the Record.pdf', 'Responses to Questions for the Record', 'Beckering'),
    ("Cobb QFR's.pdf", "QFR's", 'Cobb'),
    ("Gupta Responses to QFR's.pdf", "Responses to QFR's", 'Gupta'),
    ('Stone Responses to QFRs.pdf', 'Responses to QFRs', 'Stone'),
    ('questions-for-the-record-for-chris-magnus&download=1', 'questions-for-the-record', 'for-chris-magnus'),
    ('responses_to_questions_for_the_record_to_julie_callahan.pdf', 'responses_to_questions_for_the_record', 'to_julie_callahan'),
])
def test_observed_question_labels_and_literal_subjects(engine, name, label, subject):
    result = checked(engine, name)
    f, = fields(result, 'label')
    assert f['raw'] == label
    assert not f['code'] and not f['context'] and not f['candidates']
    assert subject in [f['raw'] for f in fields(result, 'subject_token')]


@pytest.mark.parametrize('name,label', [
    ('Adams Responses to QFRs1.pdf', 'Responses to QFRs'),
    ('211213 Vidal Answers to QFRs FINAL (1).pdf', 'Answers to QFRs'),
    ('Arianna Freeman Written Responses to Questions for the Record_9c852b58-a78b-4d47-b77b-1eaee60cd880.pdf', 'Written Responses to Questions for the Record'),
    ('2025-05-21_qfrresponses_edlow.pdf', 'qfrresponses'),
    ('051414_ONDCP_Hearing_on_Rx_QFR_response_FINAL_2.pdf', 'QFR_response'),
    ('10_2_18_Drug_Caucus_QFRs_FDA_response.pdf', 'QFRs'),
    ('McAleenan Responses to Whitehouse QFRs.pdf', 'QFRs'),
])
def test_observed_internal_or_compound_wording_without_inferred_roles(engine, name, label):
    result = checked(engine, name)
    assert label in [f['raw'] for f in fields(result, 'label')]
    assert not fields(result, 'member_surname_token')


@pytest.mark.parametrize('name,label', [
    ('011525_rubio_testimonypdf', 'testimony'),
    ('ippolito-medical-debt-written-testimonypdf', 'written-testimony'),
    ('rogers-opening-statementpdf', 'opening-statement'),
    ('s-hrg-119-328_transcriptpdf', 'transcript'),
    ('vaden-responses-to-questions-for-the-recordpdf', 'responses-to-questions-for-the-record'),
    ('aenlle-rocha-responses-to-qfrspdf', 'responses-to-qfrs'),
])
def test_observed_hanging_pdf_is_not_an_extension_and_does_not_hide_label(engine, name, label):
    result = checked(engine, name)
    assert label in [f['raw'] for f in fields(result, 'label')]
    assert not fields(result, 'extension')
    assert 'pdf' in [f['raw'] for f in fields(result, 'ignored_suffix')]


@pytest.mark.parametrize('label', ['QFR', 'QFRs', "QFR's", 'QFR’s', 'Questions for the Record',
                                  'Written Responses to QFRs', 'QFRResponses', 'Responses for Questions for the Record'])
def test_constructed_standalone_and_prefix_suffix_forms_share_the_wording(engine, label):
    for name in [label+'.pdf', label+' Smith.pdf', 'Smith '+label+'.pdf']:
        result = checked(engine, name)
        assert label in [f['raw'] for f in fields(result, 'label')]


@pytest.mark.parametrize('name', [
    'AQFRs.pdf', 'XQFRResponses.pdf', 'QFRschedules.pdf', 'Questions for the Recording.pdf',
    'Responses to Market Conditions.pdf', 'National Response Plan.pdf', 'sammypdf.pdf',
    'testimonypdfdraft.pdf', 'statementpdfworker.pdf', 'testimonypdff.pdf',
    'HHRG-119-IF00-Wstate-QFRResponses-20250318.pdf',
    'HHRG-119-IF00-Wstate-Testimonypdf-20250318.pdf',
])
def test_constructed_word_endings_and_protected_ids_do_not_acquire_labels(engine, name):
    assert not fields(checked(engine, name), 'label')


@pytest.mark.parametrize('name,subject,suffix', [
    ('QFRResponses Smithpdf', 'Smith', 'pdf'),
    ('Questions for the Record sammypdf.pdf', 'sammy', 'pdf'),
    ('Testimony tobias-tedtimony.pdf', 'tobias', '-tedtimony'),
])
def test_constructed_explicit_subject_keeps_existing_hanging_suffix_policy(engine, name, subject, suffix):
    result = checked(engine, name)
    assert subject in [f['raw'] for f in fields(result, 'subject_token')]
    assert suffix in [f['raw'] for f in fields(result, 'ignored_suffix')]


def test_observed_date_prefix_keeps_its_components_and_subject_remainder(engine):
    result = checked(engine, '041122 Corrected Christie QFRs.pdf')
    assert '041122' in [f['raw'] for f in fields(result, 'date_token')]
    assert 'Corrected Christie' in [f['raw'] for f in fields(result, 'subject_token')]
    assert not fields(result, 'generic_identifier')
    assert not any(f['candidates'] for f in fields(result, 'date_token'))


def test_observed_dated_qfr_layout_retains_uuid_and_date(engine):
    name = 'QFR Responses - Bridges - 2022-07-12_86dc0c3c-ede4-435f-8ad0-5a7aab21b9af.pdf'
    result = checked(engine, name)
    assert fields(result, 'date_token')[0]['candidates'] == ['2022-07-12']
    assert fields(result, 'opaque_uuid')[0]['raw'] == '86dc0c3c-ede4-435f-8ad0-5a7aab21b9af'
    assert fields(result, 'subject_token')[0]['raw'] == 'Bridges'


def test_observed_house_document_slots_remain_authoritative(engine):
    result = checked(engine, 'HHRG-116-GO00-20200715-QFR012.pdf')
    assert fields(result, 'document_token')[0]['raw'] == 'QFR'
    assert fields(result, 'document_number')[0]['raw'] == '012'
    assert not fields(result, 'label')


def test_observed_question_subject_keeps_both_numeric_components(engine):
    name = 'Responses-to-Questions-for-the-Record-1-Lazarus-1.pdf'
    result = checked(engine, name)
    assert {(f['raw'], f['start'], f['end']) for f in fields(result, 'generic_identifier')} == {
        ('1', 38, 39), ('1', 48, 49),
    }
    assert 'Lazarus' in [f['raw'] for f in fields(result, 'subject_token')]


@pytest.mark.parametrize('name,numbers,remainder', [
    ('1-Smith-2.pdf', ['1','2'], 'Smith'),
    ('Testimony 1-Smith-2.pdf', ['1','2'], 'Smith'),
    ('Questions for the Record 1-2-3-Smith-4.pdf', ['1','2','3','4'], 'Smith'),
    ('2020-01-01-Smith-2.pdf', ['2'], 'Smith'),
    ('1-Smith-2024-02-29.pdf', ['1'], 'Smith'),
])
def test_constructed_fallback_keeps_components_at_both_ends(engine, name, numbers, remainder):
    result = checked(engine, name)
    found = {(f['start'],f['raw']) for f in fields(result, 'generic_identifier')}
    assert [raw for _,raw in sorted(found)] == numbers
    assert remainder in [f['raw'] for kind in ('name_token','subject_token') for f in fields(result, kind)]


@pytest.mark.parametrize('name', ['Testimony 1-Smith-S42.pdf', '1-Smith-S42.pdf',
                                  'Testimony 1-Smith-S 42.pdf', 'Testimony 1-Smith-S-42.pdf'])
def test_constructed_remainder_does_not_reinterpret_assigned_measure_numbers(engine, name):
    result = checked(engine, name)
    assert [f['raw'] for f in fields(result, 'generic_identifier')] == ['1']
    assert '42' in [f['raw'] for f in fields(result, 'measure_number')]


def test_many_nested_fallback_components_are_bounded():
    subprocess.run([sys.executable, '-c',
        'from house_naming import Engine; r=Engine().extract("1-" * 1000 + "Smith-2.pdf"); '
        'ids={(f["start"], f["raw"]) for m in r["observations"] for f in m["fields"] if f["name"]=="generic_identifier"}; '
        'assert len(ids)==1001'], check=True, capture_output=True, timeout=8)


@pytest.mark.parametrize('name,selected', [
    ('19-13_02-14-19', '02-14-19'),
    ('19-14_02-26-19.pdf', '02-26-19'),
    ('19-18_02-28-19.pdf', '02-28-19'),
    ('Questions for the Record 19-13_02-14-19.pdf', '02-14-19'),
])
def test_remainder_cannot_revive_rejected_overlapping_date(engine, name, selected):
    result = checked(engine, name)
    assert {f['raw'] for f in fields(result, 'date_token')} == {selected}
    assert any(s['reason']=='Overlaps a structured or already assigned token.'
               and s['rule']=='date-separated' for s in result['suppressed'])


def test_long_compound_wording_is_bounded():
    subprocess.run([sys.executable, '-c',
        'from house_naming import Engine; e=Engine(); '
        'e.extract("Responses to Written Questions for the Record_" * 300 + "pdf"); '
        'e.extract("A" * 15000 + "_testimonypdfdraft.pdf")'],
        check=True, capture_output=True, timeout=8)
