"""Real blank-kind labels and counterexamples from the complete label audit."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, filename):
    result = engine.extract(filename)
    assert ''.join(p['raw'] for p in result['pieces']) == filename
    for observation in result['observations']:
        for field in observation['fields']:
            assert filename[field['start']:field['end']] == field['raw']
    assert all(result[k] == value for k, value in engine.parse(filename).items())
    return result['metadata']


@pytest.mark.parametrize('filename,kind', [
    ('01 12 2022 -- Business Meeting.pdf', 'business-meeting'),
    ('01 15 25 Nominations -- Rubio.pdf', 'nomination'),
    ('Nomination Hearing of Dana Lindenbaum.pdf', 'nomination'),
    ('2021-04-09 Final ATA 2021 Unclassified Report.pdf', 'report'),
    ('02JUN2020.CIVICARX.VANTRIESTE.STMNT.pdf', 'statement'),
    ('05JUN2019GraySMNT.pdf', 'statement'),
    ('BEGICH stmt.docx', 'statement'),
    ('61422_Amendments.zip', 'amendment-collection'),
    ('GSA Committee Resolution -- Moakley Courthouse.pdf', 'committee-resolution'),
    ('7.1.20-27-gsa-resolutions.pdf', 'committee-resolution'),
    ('GSA Committee Resolutions approved.pdf', 'committee-resolution'),
    ('Committee Resolution.pdf', 'committee-resolution'),
    ('AbbVie Responses.pdf', 'response'),
    ('Smith Response.pdf', 'response'),
    ('FY19 Border Security Supplemental Appropriations Summary.pdf', 'summary'),
    ('116-HR1-RCP-SummaryOfChanges.pdf', 'summary'),
    ('BILL-TO-BILL_118hr8282ih_to_RCP_8282_xml.pdf', 'bill-comparison'),
    ("FY20 CJS Manager's Package.pdf", 'managers-package'),
    ('fy2020-agriculture-managers-package', 'managers-package'),
    ('AF Military Justice Process Slide_03-06-19.pdf', 'slides'),
    ('aaro-slides-112124', 'slides'),
    ('Master Amendment List EARN Act.pdf', 'amendment-list'),
    ('Drug Amendment List.pdf', 'amendment-list'),
    ("Description of the Chairman's Mark MEPA_Final.pdf", 'mark-description'),
    ('Description of the Chairmans Mark.pdf', 'mark-description'),
    ("Clean Energy for America Act - Chairman's Mark.pdf", 'chair-mark'),
    ('Chairmans Mark.pdf', 'chair-mark'),
    ("Modifications to the Chairman's Mark 072519.pdf", 'mark-modification'),
    ('modification-of-the-chairmans-mark-of-the-modernizing-act', 'mark-modification'),
    ('Clean_Energy_for_America_Act_Chairmans_Modified_Mark.pdf', 'chair-mark'),
    ('Sen Manchin Remarks.pdf', 'remarks'),
    ('Simons oral remarks final.pdf', 'remarks'),
    ('Written Remarks Senate Commerce.pdf', 'remarks'),
    ('Lisa Su Prepared Remarks.pdf', 'remarks'),
    ('economic_security_issue_brief.pdf', 'issue-brief'),
    ('EAC_Clearinghouse Resources Appendix1.pdf', 'appendix'),
    ('SCA_Boyko_11_28_18_appendix.pdf', 'appendix'),
    ('Smith Attachment.pdf', 'attachment'),
    ('Public Exhibits to UBS Bank USA OCC Application.pdf', 'exhibit-collection'),
    ('Brink_Committee_Memo.pdf', 'committee-memorandum'),
    ('02-04-21_117th_rules_memorandum.pdf', 'rules-memorandum'),
    ('USPS_flyer.pdf', 'flyer'),
    ('Clean Energy for America Act - Revenue Estimate.pdf', 'revenue-estimate'),
    ('Kristen Clarke Responses for the Record.pdf', 'questions-for-record-response'),
    ('AP Answers for the Record.pdf', 'questions-for-record-response'),
    ('Dellinger Written Questions for Record.pdf', 'questions-for-record'),
    ('Exhibit List (FOR RELEASE).pdf', 'exhibit-list'),
    ('Afghanistan Opening Stmt.pdf', 'opening-statement'),
    ('Fighting_Fraud_Pamphlet.pdf', 'pamphlet'),
    ('Insulin Scatterplot FINAL.pdf', 'graphic'),
    ('02_SMC_graphic.pdf', 'graphic'),
    ('Older Americans Act Brochure.pdf', 'brochure'),
    ('shortbio-weimer.pdf', 'biography'),
    ('Witness-Bios-for-Web_Counter-Kleptocracy-Hearing.pdf', 'biography'),
    ('03-04-20_house_small_business_committee_fy_2021_budget_views_and_estimates.pdf', 'budget-views-and-estimates'),
    ('gas-prices-oil-profits-fact-sheet-5.6.26.pdf', 'fact-sheet'),
    ('FINAL_TRASNCRIPTION.doc', 'transcript'),
    ('McCord Opening Statemet to SASC.pdf', 'opening-statement'),
    ('Michael Walsh Opening statmement.pdf', 'opening-statement'),
    ('reponses-to-questions-from-the-record-to-david-samuel-johnson', 'questions-for-record-response'),
    ('Sweeney Responses to Written Quetions for the Record.pdf', 'questions-for-record-response'),
    ('further-response-to-senator-wyden-question-for-the-record-to-robert-f-kennedy-jr', 'questions-for-record-response'),
])
def test_literal_genre_reaches_kind(engine, filename, kind):
    assert checked(engine, filename).get('document_kind') == [kind]


@pytest.mark.parametrize('filename,kind', [
    ('Business Meeting Transcript.pdf', 'transcript'),
    ('GSA-resolutions-business-meeting-11-20-2024-final.pdf', 'committee-resolution'),
    ('Smith Testimony for Nomination.pdf', 'testimony'),
    ('Managers Package Summaries 2.8.24 (FINAL) (Post Mark Up)(2).pdf', 'summary'),
    ('amendments-to-the-chairmans-mark-for-the-prescription-drug-pricing-reduction-act-of-2019', 'amendment-collection'),
    ('Summary slide.pdf', 'slides'),
    ('Statement about a Report.pdf', 'statement'),
    ('Report on Nomination Procedures.pdf', 'report'),
    ('Transcript about a Business Meeting.pdf', 'transcript'),
])
def test_specific_document_not_its_subject_or_context(engine, filename, kind):
    assert checked(engine, filename)['document_kind'] == [kind]


@pytest.mark.parametrize('filename', [
    '02 09 22 Afghanistan Humanitarian Crisis and US Response.pdf',
    '05 10 23 Conflict in Sudan Options for an Effective Policy Response.pdf',
    'Hearing about the Syria Study Group Report.pdf',
    'Hearing on Rules Memorandum Policy.pdf',
    'Summary Judgment Reform.pdf',
    'Report Cards for Schools.pdf',
    'Reported.pdf', 'Modified.pdf', 'ReportCardReformAct.pdf',
    'documents-acquire.py.before', 'Other Documents.zip',
    'house_100940_documents_HHRG_113_WM01_20130605_SD002_pdf',
    '106791.none', '100031.xml', 'SCA_Jones_09_05_19.pdf',
    'quetions.pdf', 'Smith.pdf',
])
def test_unestablished_genres_stay_unestablished(engine, filename):
    assert not checked(engine, filename).get('document_kind')


@pytest.mark.parametrize('subject', ['NominationReformAct', 'BusinessMeetingReformAct', 'ReportPolicyAct',
                                    'SummaryJudgmentAct', 'ResponsePolicyAct', 'RulesMemorandumReformAct'])
def test_bill_title_is_not_a_document_label(engine, subject):
    row = checked(engine, f'BILLS-119-HR123-{subject}-ih.pdf')
    assert not {'nomination', 'business-meeting', 'report', 'summary', 'response', 'rules-memorandum'} & set(row['document_kind'])


@pytest.mark.parametrize('label', ['Business Meeting', 'Nomination', 'Report', 'Rules Memorandum'])
def test_witness_id_never_supplies_a_genre(engine, label):
    row = checked(engine, f'HHRG-119-IF00-Wstate-{label}-20250318.pdf')
    assert row['document_kind'] == ['witness-statement']
    assert row['witness_id'] == [label]


def test_multiple_actual_genres_and_raw_labels_survive(engine):
    row = checked(engine, 'Groginsky Testimony, Summary, and Bio2.pdf')
    assert set(row['document_kind']) == {'testimony', 'summary', 'biography'}
    assert set(row['label']) == {'Testimony', 'Summary', 'Bio'}


def test_nomination_subject_date_and_part_survive(engine):
    row = checked(engine, '01 19 2021 Nominations -- Blinken Part 1.pdf')
    assert row['document_kind'] == ['nomination']
    assert row['label'] == ['Nominations']
    assert row['subject_token'] == ['Blinken']
    assert row['part_number'] == ['1']
    assert row['date_token_candidates'] == ['2021-01-19']
    assert not row.get('witness_id')


def test_business_meeting_label_and_date_survive(engine):
    row = checked(engine, '01 12 2022 -- Business Meeting.pdf')
    assert row['label'] == ['Business Meeting']
    assert '2022-01-12' in row['date_token_candidates']


def test_rules_memo_retains_congress_reference_and_date(engine):
    row = checked(engine, '02-04-21_117th_rules_memorandum.pdf')
    assert row['label'] == ['rules_memorandum']
    assert row['date_token'] == ['02-04-21']
    # No calendar century or primary Congress is inferred from an ordinal.
    assert not row.get('congress')


@pytest.mark.parametrize('filename,kind', [
    ('Hearing on the High Plains_Testimony_Amy France_06.26.241.pdf', 'testimony'),
    ('03-16-2022 - SCIA Hearing on Buy Native American Written Testimony - IAC.pdf', 'testimony'),
    ("05.21.19 - Hearing on Renewables and Efficiency - Murkowski's Opening Statement.pdf", 'opening-statement'),
    ('BILLS-119pih-CommitteePrint-U1.pdf', 'committee-print'),
    ('BILLS-119pih-LegislativeTextasReportedOutofCommittee.pdf', 'legislative-text'),
    ('BILLS-119---SC-AP-FY2027-FServices-Amdt-1.pdf', 'amendment'),
    ('BILLS-114207rfh-AmendmentintheNatureofaSubstitutetoHR207-U1.pdf', 'amendment'),
    ('10_2_18_Drug_Caucus_QFRs_FDA_response.pdf', 'questions-for-record-response'),
    ('1-22-21 -- Business Meeting - Yellen Nomination.pdf', 'business-meeting'),
])
def test_full_corpus_existing_signal_survives(engine, filename, kind):
    row = checked(engine, filename)
    assert kind in row['document_kind']
    if kind == 'questions-for-record-response':
        assert 'questions-for-record' not in row['document_kind']
    if kind == 'business-meeting':
        assert 'nomination' not in row['document_kind']
        assert 'Nomination' in row['label']


@pytest.mark.parametrize('filename', [
    '07 27 23 -- Haiti Next Steps on the International Response.pdf',
    '07-27-23__haiti-next-steps-on-the-international-response',
    'score-of-the-modification-of-the-chairmans-mark-of-the-taxpayer-assistance-and-service-act',
])
def test_full_corpus_topic_counterexamples(engine, filename):
    assert not checked(engine, filename).get('document_kind')


def test_measure_digits_do_not_become_a_subject_counter(engine):
    row = checked(engine, 'S1_Business_Meeting.pdf')
    assert row['subject_token'] == ['S1']
    assert row['measure_references'] == ['s1']
    assert not row.get('local_number_token')


def test_estimated_revenue_effects_describe_the_mark(engine):
    row = checked(engine, 'estimated-revenue-effects-of-the-chairmans-mark-of-the-enhancing-american-retirement-now-earn-act')
    assert row['document_kind'] == ['revenue-estimate']
    assert 'estimated-revenue-effects' in row['label']
    assert 'chairmans-mark' in row['label']


def test_lowercase_report_cards_are_a_topic(engine):
    assert not checked(engine, 'report_cards_for_schools.pdf').get('document_kind')


@pytest.mark.parametrize('filename', [
    '09 24 19 The Path Forward Key Findings From the Syria Study Group Report.pdf',
    'oversight-hearing-gao-report-tribal-access-spectrum-promoting-communications-services-indian.xml',
    '06 18 2020 06 30 2020 -- COVID-19 and US International Pandemic Preparedness, Prevention, and Response.pdf',
    'covid-19-an-update-on-the-federal-response.xml',
])
def test_reviewed_report_and_response_topics_keep_literal_labels(engine, filename):
    row = checked(engine, filename)
    assert row.get('label')
    assert not row.get('document_kind')


def test_observed_questions_of_the_record_spelling(engine):
    row = checked(engine, 'reponses-to-questions-of-the-record-to-andrew-g-biggs')
    assert row['document_kind'] == ['questions-for-record-response']
