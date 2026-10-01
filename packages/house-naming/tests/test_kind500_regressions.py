"""Literal evidence and negative controls from the 500-per-kind manual audit."""
import pytest
from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def read(engine, name):
    result = engine.extract(name)
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for observation in result['observations']:
        for field in observation['fields']:
            assert name[field['start']:field['end']] == field['raw']
    return result['metadata']


@pytest.mark.parametrize('name,field,value', [
    ('CRPT-116-HA00-Vote1-8-20191016.pdf', 'document_identifier', '1-8'),
    ('CRPT-117-MH00-Vote1-6-20211208.pdf', 'document_identifier', '1-6'),
    ('HRPT-114-HRept114-___.pdf', 'number_placeholder', '___'),
    ('BILLS-113hr_297ih-U1.pdf', 'measure_number', '297'),
    ('BILLS-113hr_297ih-U1.pdf', 'document_kind', 'bill-numbered'),
    ('BILLS-115HR0625ih.pdf', 'document_kind', 'bill-numbered'),
    ('BILLS-113hjres70-PIH.pdf', 'version_token_label', 'Pre-introduced measure'),
    ('23-38-04-26-2023-transcript', 'date_token_candidates', '2023-04-26'),
    ('050824personneltranscript.pdf', 'document_kind', 'transcript'),
    ('09182025nominationtranscript.pdf', 'document_kind', 'transcript'),
    ('050824chairmanwhitehouseopeningstatement.pdf', 'document_kind', 'opening-statement'),
    ('general-langley-opening-statements', 'document_kind', 'opening-statement'),
    ('griffith-tesitmony', 'document_kind', 'testimony'),
    ('keohtestimony', 'document_kind', 'testimony'),
    ('050825_farkas_testimonydocx', 'document_kind', 'testimony'),
    ('Witness-Biographies_Upholding-OSCE-Commitments-in-Hungary-and-Poland_For-Web.pdf', 'document_kind', 'biography'),
    ('H.R. 31 Managers_Amendment.pdf', 'document_kind', 'amendment'),
    ('S. 1340 Substitute Amendment.pdf', 'document_kind', 'amendment'),
    ('BILLS -115HR2810-RCP115-23.xml', 'document_kind', 'bill-measure-list'),
    ('BILLS-115HR3312-RCP115- 49.xml', 'document_kind', 'bill-measure-list'),
    ('BILLS-117HR6531SUS-RCP117-44.pdf', 'document_kind', 'bill-measure-list'),
    ('7FD2A2A764E60CB10549ADEC8F3F5493B0AEE13204CBFA74023DA4D2D71AB38D.bills-119s68is.pdf', 'congress', '119'),
    ('7FD2A2A764E60CB10549ADEC8F3F5493B0AEE13204CBFA74023DA4D2D71AB38D.bills-119s68is.pdf', 'version_token', 'is'),
    ("07.22.20 - ENR Subcommittee Hearing - McSally's Opening Statement (as Prepared).pdf", 'qualifier_wording', 'as Prepared'),
    ('opening-statement-chair-lee-final-srwedits.pdf', 'qualifier_wording', 'final'),
    ('Prepared Testimony of Joshua Bercu - Robocall Hearing 1020.pdf', 'qualifier_wording', 'Prepared'),
    ('UPDATED Ly TESTIMONY for RAFM 07.28.2020.pdf', 'qualifier_wording', 'UPDATED'),
    ('BILLS-115HR-FC-AP-FY2019-AP00-FinalBill.pdf', 'qualifier_wording', 'Final'),
    ('BILLS-119-HR4090-A000381-Amdt-5Revised.pdf', 'revision_wording', 'Revised'),
    ('05.25.2021 Senate Finance Committee - Treasury Nominee Follow-Up QFR Responses for the Record.pdf', 'qualifier_wording', 'Follow-Up'),
    ('2025-09-16PM_QFR-Responses_Garcia.pdf', 'session_period', 'PM'),
    ('02-04-26-PM_QFR-Responses_Robbins.pdf', 'session_period', 'PM'),
    ('transcript10222020pm', 'session_period', 'pm'),
    ('transcript102022am', 'session_period', 'am'),
    ('BILLS-115-OversightPlan-F000454-Amdt-016.pdf', 'target_document_kind', 'oversight-plan'),
    ('BILLS-117-CommitteePrint-M001213-Amdt-44.pdf', 'target_document_kind', 'committee-print'),
    ('BILLS-119-ANStoCommitteePrint-H001068-Amdt-248.pdf', 'target_document_kind', 'committee-print'),
    ('BILLS-118CommitteeAuthorizationandOversightPlanih.pdf', 'document_kind', 'oversight-plan'),
    ('BILLS-117CommitteePrintih.pdf', 'document_kind', 'committee-print'),
    ('BILLS-119CommitteePrint119-Aih.pdf', 'document_kind', 'committee-print'),
    ('hr-31-managers-amendment-052219', 'short_date_token', '052219'),
    ('s1657-managers-amendment101921', 'short_date_token', '101921'),
    ('BILLS-114pih-CommitteePrintofHR______theSurfaceTransportationResearchandDevelopmentActof2015.pdf', 'number_placeholder', '______'),
    ('BILLS-115pih-DiscussionDraftofHR__DrinkingWaterSystemImprovementAct.pdf', 'number_placeholder', '__'),
    ('BILLS-1165214ih-ANStotheRepresentativePayeeFraudPreventionActof2019.pdf', 'amendment_marker', 'ANS'),
    ('BILLS-117pih-ANStotheCommitteePrint.pdf', 'target_marker', 'to'),
    ('Romney Amendment #1 to S.3392.pdf', 'target_marker', 'to'),
    ('BILLS-119HR6028ANS-HAmdt.pdf', 'amendment_marker_label', 'Amendment in the nature of a substitute'),
    ('BILLS-118HR2973ANSih.pdf', 'amendment_marker_label', 'Amendment in the nature of a substitute'),
    ('CPRT-113-HPRT-RU00-h3547-hamdt2samdt.xml', 'amendment_marker', 'hamdt'),
    ('CPRT-113-HPRT-RU00-h3547-hamdt2samdt.xml', 'measure_references', 'h3547'),
    ('BILLS-118pih-ThisDiscussionDraftresoluti.pdf', 'draft_label', 'DiscussionDraft'),
    ('BILLS-118pih-DIOAFY25SubcommitteeMark.pdf', 'fiscal_year_token', '25'),
    ('BILLS-119pih-CRFY27.pdf', 'fiscal_year_token', '27'),
    ('HRPT-113-OJCR-HR5078p2.pdf', 'part_number', '2'),
    ('BILLS-116H2507-SCD-AMD_01xmlih.pdf', 'version_token', 'ih'),
    ('BILLS-116H2507-SCD-AMD_01xmlih.pdf', 'filename_format_token', 'xml'),
    ('HRPT-115-1_1-p1-U3.pdf', 'report_subject_token', '1_1'),
    ('HRPT-115-HRes115-976.pdf', 'report_subject_token', 'HRes115-976'),
    ('All_Feinstein-Brownfield_QFR_1_to_6.docx', 'question_identifier', '1_to_6'),
    ('Robinson-Whitehouse_QFR_1-12.docx', 'question_identifier', '1-12'),
    ('updated-hearing-statement-as-given-07.30.20.pdf', 'qualifier_wording', 'updated'),
    ('Calvelli and VCSO Written Statement SASC-SF FINAL Corrected (1)1.pdf', 'qualifier_wording', 'Corrected'),
    ('41322 Final Danly SENR QFRs.pdf', 'qualifier_wording', 'Final'),
    ('Final WA QFRs.pdf', 'qualifier_wording', 'Final'),
    ('Amdt #34 - MODIFIED JSA to S. 1344 - Agenda Item 6 (FLO22791).pdf', 'qualifier_wording', 'MODIFIED'),
    ('BILLS-116ResolutionofferedbyMrNadlerih.pdf', 'offerer_token', 'MrNadler'),
    ('NOTICE OF SENATE COMMITTEE ON ENERGY NATURAL RESOURCES HEARING December 9 2025 at 1000 AM.pdf', 'time_token', '1000'),
    ('Canterbury SJQ.Public Portion.pdf', 'subject_token', 'Canterbury'),
    ('Velez-Rive SJQ Public for OneDrive.pdf', 'subject_token', 'Velez-Rive'),
    ('BILLS-113-HR4435-M000508-Amdt-EB11-Enbloc-11.pdf', 'amendment_identifier', 'EB11'),
    ('bio_hewitt-111941-am', 'time_token', '111941'),
    ('official-hearing-transcript_372019', 'date_token_candidates', '2019-03-07'),
    ('BILLS-114HR-FC-AP-FY2016-AP00-THUD.pdf', 'appropriation_subject', 'THUD'),
    ('BILLS-116-Lowey_Manager--AP--AP00-Amdt-1.pdf', 'amendment_marker', 'Manager'),
])
def test_explicit_signal(engine, name, field, value):
    assert value in read(engine, name).get(field, [])


@pytest.mark.parametrize('name,field,forbidden', [
    ('BILLS-118pih-BioEarly-U1.pdf', 'document_kind', 'biography'),
    ('BILLS-115-OversightPlan-F000454-Amdt-016.pdf', 'document_kind', 'oversight-plan'),
    ('BILLS-117-CommitteePrint-M001213-Amdt-44.pdf', 'document_kind', 'committee-print'),
    ('colmenero_letter_of_support_-_public_servants_and_colleagues.pdf', 'qualifier_wording', 'public'),
    ('notice-letter-footjoy-ip-edgepdf', 'document_kind', 'meeting-notice'),
    ('BILLS-115HR0625ih.pdf', 'document_kind', 'bill-numbered-described'),
    ('s-hrg-11910_transcript_02052025pdf', 'short_date_token', '11910'),
    ('Statement on Final Decisions.pdf', 'qualifier_wording', 'Final'),
    ('Public Health Testimony.pdf', 'qualifier_wording', 'Public'),
    ('BILLS-119-8870-B001285-Amdt-062071064-Enbloc-1.pdf', 'short_date_token', '062071'),
    ('BILLS-119-HR4435-M000508-Amdt-052219.pdf', 'short_date_token', '052219'),
    ('HHRG-117-II10-Wstate-JohnsonHR3197andHR4648M-20211014.pdf', 'measure_references', 'hr4648'),
])
def test_no_unsupported_interpretation(engine, name, field, forbidden):
    assert forbidden not in read(engine, name).get(field, [])


@pytest.mark.parametrize('name,field,value', [
    ('BILLS-118-HR2670-B001299-Amdt-3519r2.pdf','amendment_token','3519r2'),
    ('Transcript_03.01.20231.pdf','date_token','03.01.20231'),
    ('BILLS-1178GeneralServicesAdministrationsCapitalInvestmentandLeasingProgramResolutionsih.pdf','measure_number','8'),
    ('BILLS-118Xih.pdf','number_placeholder','X'),
    ('HHRG-117-II10-Wstate-JohnsonHR3197andHR4648M-20211014.pdf','witness_id','JohnsonHR3197andHR4648M'),
    ('transcript-04091900','date_token','04091900'),
    ('CRPT-117hrpt-HR51.pdf','document_kind','conference-unnumbered'),
    ('BILLS-117HRes271-HAmdt.pdf','document_kind','interchamber-amendment'),
])
def test_preserve_uncertain_literals_and_convention_names(engine, name, field, value):
    assert value in read(engine, name).get(field, [])


@pytest.mark.parametrize('name,date', [
    ('hr-31-managers-amendment-052219', '052219'),
    ('s-1041-managers-amendment-062221', '062221'),
    ('s-1441-substitute-amendment-073119', '073119'),
    ('s-2297-managers-amendment-072821', '072821'),
    ('s-482-managers-amendment-121819', '121819'),
    ('s-704-murphy-1st-degree-amendment-121119-15', '121119'),
    ('s-93-substitute-amendment-062221', '062221'),
    ('s-con-res-10-preamble-amendment-062519', '062519'),
    ('s-con-res-10-resolving-clause-amendment-062519', '062519'),
    ('s-res-206-revised-title-amendment-062519', '062519'),
    ('s-res-260-title-amendment-121119-26', '121119'),
    ('s-res-35-managers-substitute-amendment-032421', '032421'),
    ('s-res-371-resolving-clause-amendment-121119-33', '121119'),
    ('s1657-managers-amendment101921', '101921'),
    ('s2129-managers-amendment101921', '101921'),
    ('s3492-managers-amendment-032322', '032322'),
    ('sj-res-4-substitute-amendment-121119-18', '121119'),
    ('sres345-resolving-clause-amendment101921', '101921'),
])
def test_descriptive_amendment_suffix_keeps_both_readings(engine, name, date):
    meta = read(engine, name)
    assert date in meta['amendment_token']
    assert date in meta['short_date_token']
    assert not meta.get('date_token_candidates')  # No inferred century or event date.


def test_notice_heading_keeps_literal_committee_and_meeting_wording(engine):
    meta = read(engine, 'NOTICE OF SENATE COMMITTEE ON ENERGY  NATURAL RESOURCES HEARING December 9 2025 at 1000 AM.pdf')
    assert meta['committee_wording'] == ['SENATE COMMITTEE ON ENERGY  NATURAL RESOURCES']
    assert meta['meeting_wording'] == ['HEARING']
    assert meta['time_token'] == ['1000']
    assert not meta.get('timezone')


@pytest.mark.parametrize('name', ['Title Amendment111111.pdf', 'Substitute Amendment111111.pdf',
                                 'S. 1 Title Amendment999999.pdf', 'S. 1 Title Amendment777777.pdf'])
def test_descriptive_amendment_does_not_invent_a_date(engine, name):
    assert not read(engine, name).get('short_date_token')


def test_pih_display_does_not_rewrite_the_source_definition(engine):
    assert read(engine, 'BILLS-113hjres70-PIH.pdf')['version_token_label'] == ['Pre-introduced measure']
    assert engine.lookup('consideration', 'pih')['label'] == 'Pre-introduced measure; no bill number'


@pytest.mark.parametrize('name', ['121917_-lankford-testimony1', 'opening-statement_scott-111925pdf'])
def test_calendar_plausible_short_date_does_not_choose_a_four_digit_year(engine, name):
    meta = read(engine, name)
    assert not meta.get('date_token_candidates')
    assert not meta.get('short_date_token_candidates')


def test_amendment_chain_digit_does_not_establish_a_degree(engine):
    meta = read(engine, 'CPRT-113-HPRT-RU00-h3547-hamdt2samdt.xml')
    assert meta['amendment_join_token'] == ['2']
    assert not meta.get('amendment_degree')


def test_single_measure_reference_alone_is_not_a_measure_list_document(engine):
    meta = read(engine, 'BILLS-113hjres59-HAmdt2a.xml')
    assert 'bill-measure-list' not in meta.get('document_kind', [])


@pytest.mark.parametrize('name,subject', [
    ('All_Feinstein-Brownfield_QFR_1_to_6.docx', 'All_Feinstein-Brownfield'),
    ('Robinson-Whitehouse_QFR_1-12.docx', 'Robinson-Whitehouse'),
])
def test_question_ranges_keep_existing_category_and_subject(engine, name, subject):
    meta = read(engine, name)
    assert meta['document_kind'] == ['questions-for-record']
    assert meta['subject_token'] == [subject]
    assert meta['label'] == ['QFR']


def test_hanging_pdf_keeps_questionnaire_public_qualifier(engine):
    meta = read(engine, 'velez-rive-sjq-public-for-onedrivepdf')
    assert meta['qualifier_wording'] == ['public']
    assert meta['subject_token'] == ['velez-rive']


@pytest.mark.parametrize('name,expected', [
    ('Testimony_Dixon_09.152022.pdf', ['2022-09-15']),
    ('transcript-24-05-02-282024', ['2024-02-28']),
])
def test_compact_day_year_does_not_drop_preceding_month(engine, name, expected):
    meta = read(engine, name)
    assert meta['date_token_candidates'] == expected
    assert not meta.get('short_date_token_candidates')


@pytest.mark.parametrize('name,month,day,year', [
    ('Jefferson Keel Testimony July312013 FINAL.pdf','July','31','2013'),
    ('Resolution_July182022.pdf','July','18','2022'),
    ('termexpiringjune162032','june','16','2032'),
])
def test_named_month_owns_the_following_day_and_year(engine, name, month, day, year):
    meta = read(engine, name)
    assert meta['month_token'] == [month]
    assert meta['day_token'] == [day]
    assert meta['year_token'] == [year]
    assert not meta.get('short_date_token_candidates')
