"""Useful categories from precise wording, with source fields and ambiguity intact."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    for match in result['observations']:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
    return result['metadata']


@pytest.mark.parametrize('name', [
    '2023-11-02-ebm-results',
    'executive-business-meeting-results-2022-08-04',
    'Results of Executive Session to Favorably Report Pending Nominations2.pdf',
    'Mark up 1.13.22 Results.pdf',
    'results-of-open-executive-session-march-6-2024',
    'results-of-executive-session-of-november-15-2018&download=1',
])
def test_meeting_result_heading_has_a_category(engine, name):
    row = checked(engine, name)
    assert row['document_kind'] == ['meeting-results']
    assert [value.lower() for value in row['result_wording']] == ['results']
    assert not {'meeting_status', 'vote_result', 'vote_count'} & row.keys()


def test_meeting_result_retains_access_wording_and_date(engine):
    row = checked(engine, 'Results of the Open Executive Session of May 24, 2018.pdf')
    assert row['document_kind'] == ['meeting-results']
    assert row['access_wording'] == ['Open']
    assert row['meeting_wording'] == ['Executive Session']
    assert row['date_token_candidates'] == ['2018-05-24']


@pytest.mark.parametrize('name,kind', [
    ('fy26-milcon-va-senate-bill-summary&download=1', 'summary'),
    ('fy25_thud_senate_bill_summary.pdf', 'summary'),
    ('Bill Summaries.pdf', 'summary'),
    ('fy24_cjs_bill_text.pdf', 'legislative-text'),
    ('s-1840-bill-text', 'legislative-text'),
    ('budget-committee-reconciliation-legislative-text', 'legislative-text'),
    ('Legislation Text.pdf', 'legislative-text'),
    ('Growing Climate Solutions Act section by section1.pdf', 'section-by-section'),
    ('Section-by-Section Summary.xml', 'section-by-section'),
    ('section_by_section_analysis_of_the_better_mental_health_care_lower-cost_drugs_and_extenders_act.pdf', 'section-by-section'),
    ('section-by-section-description-1251', 'section-by-section'),
    ('OPENING REMARKS - Offshore Energy Hearing.pdf', 'opening-remarks'),
    ('LTG Mingus opening remarks_26 OCT_Final.pdf', 'opening-remarks'),
])
def test_precise_document_phrases_reach_public_metadata(engine, name, kind):
    assert checked(engine, name)['document_kind'] == [kind]


def test_categories_refine_subject_without_losing_fiscal_or_measure_fields(engine):
    row = checked(engine, 'fy26-milcon-va-senate-bill-summary&download=1')
    assert row['label'] == ['bill-summary']
    assert row['fiscal_year_token'] == ['26']
    assert 'fiscal_year' not in row  # Do not supply an unprinted century.
    assert row['subject_token'] == ['milcon-va-senate']
    row = checked(engine, 'S. 1157, Women and Lung Cancer Research and Preventive Services Act Section-by-Section.pdf')
    assert row['document_kind'] == ['section-by-section']
    assert row['measure_references'] == ['s1157']
    assert row['subject_token'] == ['S. 1157, Women and Lung Cancer Research and Preventive Services Act']


def test_remarks_subject_preserves_date_and_qualifier(engine):
    row = checked(engine, 'LTG Mingus opening remarks_26 OCT_Final.pdf')
    assert row['subject_token'] == ['LTG Mingus']
    assert row['date_token'] == ['26 OCT']
    assert row['qualifier_wording'] == ['Final']
    assert not {'person_id', 'author', 'meeting_date', 'date_token_candidates'} & row.keys()


@pytest.mark.parametrize('subject,category', [
    ('Bill_Summary', 'summary'),
    ('Legislative_Text', 'legislative-text'),
    ('Section-by-Section', 'section-by-section'),
])
def test_amendment_target_does_not_become_the_amendment_category(engine, subject, category):
    row = checked(engine, f'BILLS-119-{subject}-C001053-Amdt-1.pdf')
    assert category not in row['document_kind']
    assert row['target_document_kind'] == [category]
    assert row['subject_token'] == [subject]
    assert row['sponsor_bioguide_id'] == ['C001053']
    assert row['amendment_identifier'] == ['1']


@pytest.mark.parametrize('name', [
    'Survey Results.pdf', 'Research Results.pdf', 'Results of Election.pdf',
    'Business Meeting on Improving Survey Results.pdf',
    'Results of Executive Summary.pdf', 'Results of Executive Sessionary.pdf',
    'Executive Business Meeting ResultsOriented.pdf',
    'ResultsofExecutiveSession.pdf', 'Topic%20EBM Results.pdf',
    'Testimony on Report Cards.pdf', 'ReportCardReformAct.pdf',
    'Summary Judgment Reform.pdf',
    'DOJ Testimony_Harp_09.26.18_GAO Report on Juvenile....pdf',
    'Summaryston.pdf', 'Presummary.pdf', 'Remarksman.pdf',
    'Bill Summaryman.pdf', 'Legislative Textbook.pdf',
    'Section-by-Sectional.pdf', 'Opening Remarksmith.pdf',
    '106791.none', '100031.xml',
])
def test_topics_identifiers_and_adjacent_words_do_not_gain_categories(engine, name):
    row = checked(engine, name)
    assert not {'meeting-results', 'report', 'summary', 'opening-remarks',
                'legislative-text', 'section-by-section'} & set(row.get('document_kind', []))


@pytest.mark.parametrize('subject', ['Bill Summary', 'Bill Text', 'Opening Remarks',
                                     'Section-by-Section', 'EBM Results'])
def test_structured_witness_identifier_stays_protected(engine, subject):
    row = checked(engine, f'HHRG-119-IF00-Wstate-{subject}-20250318.pdf')
    assert row['document_kind'] == ['witness-statement']
    assert row['witness_id'] == [subject]


def test_generic_report_does_not_duplicate_a_committee_report(engine):
    row = checked(engine, 'HRPT-116-FY2020_MILCON_Report.pdf')
    assert row['document_kind'] == ['committee-report']
