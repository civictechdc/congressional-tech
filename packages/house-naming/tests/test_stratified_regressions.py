"""Failures from the 100-per-kind review of the retained filename catalog.

Assertions concern literal filename evidence, never verified people or contents.
"""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def metadata(engine, name, **context):
    result = engine.extract(name, **context)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
    return result['metadata']


@pytest.mark.parametrize('name', [
    'transcript-07282103', 'transcript-09292101', 'transcript11172101',
    'official-hearing-transcript_2112026pdf',
])
def test_ambiguous_compact_alias_does_not_invent_a_century(engine, name):
    row = metadata(engine, name)
    assert not any(value.startswith(('210', '211', '212'))
                   for value in row.get('date_token_candidates', []))


@pytest.mark.parametrize('name', ['wal25565pdf', 'hen20549.pdf', 'ehf19816.pdf'])
def test_lowercase_drafting_ids_reserve_their_digits(engine, name):
    row = metadata(engine, name)
    assert row['drafting_identifier']
    assert not {'short_date_token', 'date_token'} & row.keys()


def test_structured_numeric_subject_does_not_become_a_date(engine):
    row = metadata(engine, 'BILLS-119-10334-S001195-Amdt-2.pdf')
    assert row['subject_token'] == ['10334']
    assert not {'short_date_token', 'date_token'} & row.keys()


def test_unstructured_numeric_subject_keeps_only_its_identifier_role(engine):
    row = metadata(engine, 'transcript-07282103')
    assert row['generic_identifier'] == ['07282103']
    assert 'subject_token' not in row


@pytest.mark.parametrize('name', [
    'FINAL_transcript.doc', 'opening-statement-final.pdf',
    'transcript_02-03-2026.pdf', '03-04-20_witness_list.pdf',
    'official-hearing-transcript_11132025pdf',
])
def test_no_subject_remains_when_all_text_has_another_role(engine, name):
    row = metadata(engine, name)
    assert 'subject_token' not in row
    assert 'name_token' not in row


@pytest.mark.parametrize('name,subject', [
    ('Bio_and_Testimony_Blanton.pdf', 'Blanton'),
    ('Bio & Testimony - Mangual.pdf', 'Mangual'),
    ('12.12.19 Conley Written Statement.pdf', 'Conley'),
    ('143F2EF58AF97293ABECF3E00F592E3F082BF80A5CFC512006DA6E6D31E087D3.lemos-testimony-09.11.2019.pdf', 'lemos'),
    ('sonderling_testimony_fy27.pdf', 'sonderling'),
    ('Clements Responses to QFRs 9-16-20 SENR Cmte Noms Hrg.pdf', 'Clements'),
    ('Paul Smith CV April 2021.pdf', 'Paul Smith'),
    ('Feinstein-Opening-Statement-As-Delivered-2.pdf', 'Feinstein'),
    ('2024-03-20_pm_-_qfr_responses_-_snead_addendum.pdf', 'snead'),
    ('responses_to_questions_for_the_record_to_alex_adams.pdf', 'alex_adams'),
    ('Testimony_Benson1.pdf', 'Benson'),
    ('Bio_Wilcox 11.19.41 AM.pdf', 'Wilcox'),
    ("Senate Interior Appropriations Subcommittee Hearing FY 2024 President's Budget for IHS Written Testimony_Final 5.4.23.pdf",
     "Senate Interior Appropriations Subcommittee Hearing FY 2024 President's Budget for IHS"),
])
def test_subject_is_the_remaining_literal_text(engine, name, subject):
    row = metadata(engine, name)
    assert row['subject_token'] == [subject]
    assert 'name_token' not in row


@pytest.mark.parametrize('name,description', [
    ('HRPT-113-FY2014LegBranch.pdf', 'LegBranch'),
    ('HRPT-114-HR-FY2017-LaborHHSEd.pdf', 'LaborHHSEd'),
    ('HRPT-116-FY2020_Revised_302b_Report.pdf', '302b'),
    ('BILLS-114DiscussionDraftpih-ImprovingRecallTrackingAct-U1.pdf', 'ImprovingRecallTrackingAct'),
    ('BILLS-115HR424ih-GrayWolfStateManagementActof2017.pdf', 'GrayWolfStateManagementActof2017'),
    ('BILLS-114HR_____ih-HR____theOfficeofSpaceCommerceAct.pdf', 'theOfficeofSpaceCommerceAct'),
])
def test_useful_description_survives_other_recognized_fields(engine, name, description):
    assert metadata(engine, name)['description'] == [description]


@pytest.mark.parametrize('name,kind', [
    ('McGlynn Responses to Whitehouse QFRs.pdf', 'questions-for-record-response'),
    ('Witness Statement of Mr. James B. Balocki.pdf', 'witness-statement'),
    ('AbelsonSJQPublicFinal.pdf', 'questionnaire'),
    ('Anuraag Singhal Senate Questionnaire (PUBLIC).pdf', 'questionnaire'),
    ('03-04-20_hearing_notice.pdf', 'meeting-notice'),
    ('BILLS-119OversightPlanih.pdf', 'oversight-plan'),
    ('BILLS-117pih-CommitteePrint.pdf', 'committee-print'),
    ('BILLS-113-HR-FC-AP-FY2014-AP00-Amdt-003.pdf', 'amendment'),
])
def test_explicit_wording_contributes_a_category(engine, name, kind):
    assert kind in metadata(engine, name)['document_kind']


def test_qfr_questioner_and_respondent_stay_distinct(engine):
    row = metadata(engine, 'McGlynn Responses to Whitehouse QFRs.pdf')
    assert row['subject_token'] == ['McGlynn']
    assert row['questioner_token'] == ['Whitehouse']


def test_local_disclosure_category_requires_publisher_context(engine):
    assert metadata(engine, 'tt_burton.pdf', source_url='https://edworkforce.house.gov/tt_burton.pdf')['document_kind'] == ['testimony-disclosure']
    assert 'document_kind' not in metadata(engine, 'tt_burton.pdf')


@pytest.mark.parametrize('name,references', [
    ('BILLS-116HR8andHR1112ih.pdf', ['hr8', 'hr1112']),
    ('BILLS-115HR0625ih.xml', ['hr625']),
    ('CPRT-114-HPRT-RU00-SAHR34.pdf', ['hr34']),
])
def test_all_explicit_measure_references_have_normalized_join_keys(engine, name, references):
    assert metadata(engine, name)['measure_references'] == references


def test_reference_normalization_does_not_require_machine_sized_integers(engine):
    number = '9' * 5000
    assert metadata(engine, 'HR' + number + '.pdf')['measure_references'] == ['hr' + number]


def test_drafting_context_does_not_establish_a_bill_version(engine):
    row = metadata(engine, 'BILLS-117-H3894-SC-MNGR_01-B001303-Amdt-14.pdf')
    assert 'Sponsor Change' not in row.get('version_token_label', [])
    assert 'H3894-SC-MNGR_01' in row['subject_token']
    assert row['measure_number'] == ['3894']
    assert row['measure_references'] == ['h3894']


def test_local_drafting_prefix_keeps_its_short_reference(engine):
    row = metadata(engine, 'BILLS-117-H550-SCD-AMD_01-B001275-Amdt-11.pdf')
    assert row['measure_references'] == ['h550']
    assert 'version_token' not in row


def test_fiscal_year_and_publication_codes_are_consistent(engine):
    row = metadata(engine, 'BILLS-116--AP--AP00-FY2020EW_Bill.pdf')
    assert row['fiscal_year'] == ['2020']
    row = metadata(engine, 'CRPT-114HRPT-HR644-JES.pdf')
    assert row['publication_type'] == ['hrpt']
    assert row['measure_type'] == ['hr']


def test_download_alias_does_not_reclassify_amendment_number(engine):
    row = metadata(engine, 'hassan-s-163-amendment-2pdf')
    assert row['amendment_token'] == ['2']
    assert row['subject_token'] == ['hassan']
    assert 'generic_identifier' not in row


@pytest.mark.parametrize('name', [
    'Final Creek.pdf', 'Statement on Final Decisions.pdf',
    'HHRG-119-IF00-Wstate-Benson1-20250101.pdf',
    'BILLS-119ANSServices.pdf', 'Research and Development.pdf',
])
def test_controls_keep_source_text_and_avoid_person_inference(engine, name):
    row = metadata(engine, name)
    assert not {'member_surname_token', 'sponsor_bioguide_id'} & row.keys()
    if 'Benson1' in name:
        assert row['witness_id'] == ['Benson1']
    if name == 'Statement on Final Decisions.pdf':
        assert row['subject_token'] == ['on Final Decisions']


def test_explicit_future_date_and_short_year_are_not_repaired(engine):
    assert metadata(engine, 'Transcript-2103-07-28.pdf')['date_token_candidates'] == ['2103-07-28']
    assert 'date_token_candidates' not in metadata(engine, 'Testimony-07-28-21.pdf')


@pytest.mark.parametrize('suffix', ['U1', 'RCP115-77', 'IETC', 'HAmdt', 'xml', 'SD001'])
def test_technical_suffix_is_not_promoted_to_title(engine, suffix):
    assert 'description' not in metadata(engine, f'BILLS-115HR998ih-{suffix}.xml')
