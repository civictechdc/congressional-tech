"""Reviewed filename wording, separate from document contents and source types."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def labels(engine, filename, rule):
    result = engine.extract(filename)
    assert all(result[k] == v for k, v in engine.parse(filename).items())
    assert ''.join(p['raw'] for p in result['pieces']) == filename
    found = [f for m in result['observations'] if m['rule'] == rule for f in m['fields']]
    for field in found:
        assert field['name'] == 'label'
        assert filename[field['start']:field['end']] == field['raw']
        assert field['code'] is None and field['context'] is None
    return [f['raw'] for f in found]


@pytest.mark.parametrize('filename,expected', [
    ('BILLS-1197567pih-ManagersAmendment.pdf', 'ManagersAmendment'),
    ('BILLS-119pih-ManagersAmendmenttotheANS.pdf', 'ManagersAmendmenttotheANS'),
    ("Manager's Amendment S. 163.pdf", "Manager's Amendment"),
    ('S.J.Res.17_Managers_Amendement.pdf', 'Managers_Amendement'),
    ('s133managersamendment.pdf', 'managersamendment'),
    ('s265managersamendment.pdf', 'managersamendment'),
    ('s1462_managers_amendmentpdf', 'managers_amendment'),
    ('fy24-cjs-managers-amendment&download=1', 'managers-amendment'),
    ('hr965-managers-amendment101921', 'managers-amendment'),
    ('S.Res.106_Resolving_Clause_Managers_Amendment2.pdf', 'Managers_Amendment'),
    ('Manager’s Amendment to the AINS.pdf', 'Manager’s Amendment to the AINS'),
])
def test_managers_amendment_wording(engine, filename, expected):
    assert labels(engine, filename, 'managers-amendment-wording') == [expected]


@pytest.mark.parametrize('filename,expected', [
    ('01-09-20_hearing_notice.pdf', 'hearing_notice'),
    ('01-19-22_remote_hearing_notice.pdf', 'remote_hearing_notice'),
    ('updated_07-02-20_hybrid_hearing_notice.pdf', 'hybrid_hearing_notice'),
    ('07-22-19_field_hearing_notice.pdf', 'field_hearing_notice'),
    ('02-03-22_markup_notice.pdf', 'markup_notice'),
    ('05-13-20_sbc_forum_announcement.pdf', 'forum_announcement'),
    ('03-04-20_views_and_estimate_notice.pdf', 'views_and_estimate_notice'),
    ('Agenda 1-23-25 SENR Cmte Bus Mtg.pdf', 'Agenda'),
    ('NOTICE OF SENATE COMMITTEE HEARING December 2 2025.pdf', 'NOTICE'),
    ('Notice Letter Footjoy IP EDGE.pdf', 'Notice'),
    ('the-following-agenda-to-be-considered-06-17-2026', 'the-following-agenda-to-be-considered'),
    ('Agenda.pdf', 'Agenda'),
    ('notice_of_meeting.pdf', 'notice'),
])
def test_explicit_notice_and_agenda_wording(engine, filename, expected):
    assert labels(engine, filename, 'notice-agenda-wording') == [expected]


@pytest.mark.parametrize('filename,expected', [
    ('116-HR1-RCP-SummaryOfChanges.pdf', 'SummaryOfChanges'),
    ('bill_summary_-_energy_and_water_development_fiscal_year_2024_appropriations_bill.pdf', 'bill_summary'),
    ('Section-by-Section Summary.pdf', 'Section-by-Section Summary'),
    ('section_by_section_analysis_of_the_better_mental_health_care_lower-cost_drugs_and_extenders_act.pdf', 'section_by_section_analysis'),
    ('section-by-section-description-1251', 'section-by-section-description'),
    ('uniformed-services-leave-parity-act-section-by-sectionpdf', 'section-by-section'),
    ('Summary.pdf', 'Summary'),
    ('Managers Package Summaries 2.8.24 (FINAL) (Post Mark Up)(2).pdf', 'Summaries'),
    ('Simmons Testimony - Attachment_GEO VISION Exec Summary_6-20-19.pdf', 'Exec Summary'),
    ('FE359F2398CC6824.gas-prices-oil-profits-fact-sheet-5.6.26.pdf', 'fact-sheet'),
    ('Joint Explanatory Statement.pdf', 'Joint Explanatory Statement'),
    ('Executive Summary.pdf', 'Executive Summary'),
    ('Transcript Errata.pdf', 'Transcript Errata'),
    ('Errata Sheet.pdf', 'Errata Sheet'),
    ('FactSheets.pdf', 'FactSheets'),
])
def test_summary_and_components(engine, filename, expected):
    assert labels(engine, filename, 'summary-component-wording') == [expected]


@pytest.mark.parametrize('filename', [
    'the_presidents_2024_trade_policy_agenda.pdf',
    'Wyden Statement at Finance Committee Hearing Examining the Presidents 2022 Trade Policy Agenda2.pdf',
    'Agenda Item 20.pdf',
    'TheRegulatoryAgendaClarityAct.pdf',
    'is-the-dmcas-notice-and-takedown-system-working-in-the-21st-century',
    'HearingNoticeman.pdf', 'Forum_Announcementman.pdf',
])
def test_topics_and_references_are_not_agenda_documents(engine, filename):
    assert labels(engine, filename, 'notice-agenda-wording') == []


@pytest.mark.parametrize('rule,filename', [
    ('managers-amendment-wording', 'PreManagersAmendment.pdf'),
    ('managers-amendment-wording', 'ManagersAmendmentman.pdf'),
    ('managers-amendment-wording', 'Topic%20ManagersAmendment.pdf'),
    ('summary-component-wording', 'Summaryston.pdf'),
    ('summary-component-wording', 'Presummary.pdf'),
    ('summary-component-wording', 'Topic%20Summary.pdf'),
    ('summary-component-wording', 'Factsheetman.pdf'),
    ('managers-amendment-wording', 'HHRG-119-IF00-Wstate-ManagersAmendment-20250318.pdf'),
    ('notice-agenda-wording', 'HHRG-119-IF00-Wstate-Hearing_Notice-20250318.pdf'),
    ('summary-component-wording', 'HHRG-119-IF00-Wstate-Section-by-Section-20250318.pdf'),
])
def test_word_boundaries_and_protected_slots(engine, rule, filename):
    assert labels(engine, filename, rule) == []


def test_mixed_wording_does_not_replace_existing_fields(engine):
    result = engine.extract('Groginsky Testimony, Summary, and Bio2.pdf')
    fields = [f for m in result['observations'] for f in m['fields']]
    assert {f['raw'] for f in fields if f['name'] == 'label'} == {'Testimony', 'Summary', 'Bio'}
    result = engine.extract("S. 1573 Manager's Amendment Section by Section.pdf")
    fields = [f for m in result['observations'] for f in m['fields']]
    assert {f['raw'] for f in fields if f['name'] == 'label'} == {"Manager's Amendment", 'Section by Section'}
    assert any(f['name'] == 'measure_number' and f['raw'] == '1573' for f in fields)


def test_specific_phrase_keeps_the_prior_generic_label(engine):
    result = engine.extract('Joint Explanatory Statement.pdf')
    assert {f['raw'] for m in result['observations'] for f in m['fields'] if f['name'] == 'label'} == {
        'Statement', 'Joint Explanatory Statement'}


def test_literal_hybrid_remote_words_do_not_verify_access(engine):
    result = engine.extract('01-19-22_remote_hearing_notice.pdf')
    assert not any(f['name'] in {'access_wording', 'status', 'meeting_id'} for m in result['observations'] for f in m['fields'])
