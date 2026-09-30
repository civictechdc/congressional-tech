"""Literal planning phrases and fiscal markers preserve their original context."""
import pytest

from house_naming import Engine


NEW_RULES = {'budget-views-wording', 'oversight-plan-wording', 'joined-fiscal-year'}


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[key] == value for key, value in engine.parse(name).items())
    assert ''.join(piece['raw'] for piece in result['pieces']) == name
    added = [match for match in result['observations'] if match['rule'] in NEW_RULES]
    for match in added:
        for field in match['fields']:
            assert name[field['start']:field['end']] == field['raw']
            assert match['start'] <= field['start'] <= field['end'] <= match['end']
            assert field['code'] is None and field['label'] is None
            assert field['context'] is None and not field['candidates']
    return result, added


@pytest.mark.parametrize('name,label', [
    ('03-04-20_house_small_business_committee_fy_2021_budget_views_and_estimates.pdf', 'budget_views_and_estimates'),
    ('03-04-20_views_and_estimate_notice.pdf', 'views_and_estimate'),
    ('BILLS-114pih-FY16BudgetViewsandEstimates.pdf', 'BudgetViewsandEstimates'),
    ('BILLS-115pih-BudgetViewsandEstimatesFY18.pdf', 'BudgetViewsandEstimates'),
    ('BILLS-116pih-ViewsandEstimatestext-U2.pdf', 'ViewsandEstimatestext'),
    ('BILLS-118FY2024ViewsandEstimatesih.pdf', 'ViewsandEstimates'),
    ('Budget Views and Estimates Text.pdf', 'Budget Views and Estimates Text'),
    ('Views and Estimatespdf.pdf', 'Views and Estimates'),
    ('budget-views-and-estimates&download=1', 'budget-views-and-estimates'),
])
def test_budget_phrase(engine, name, label):
    _, added = checked(engine, name)
    matches = [match for match in added if match['rule'] == 'budget-views-wording']
    match, = matches
    assert match['fields'][0]['raw'] == label


@pytest.mark.parametrize('name,label', [
    ('BILLS-114pih-CommitteeOversightPlan.pdf', 'CommitteeOversightPlan'),
    ('BILLS-115-AuthorizationandOversightPlan-B001292-Amdt-006.pdf', 'AuthorizationandOversightPlan'),
    ('BILLS-115-AuthorizationandOversightPlanforthe115thCongress-D000399-Amdt-1.pdf', 'AuthorizationandOversightPlan'),
    ('BILLS-118-118thAuthorizationandOversightPlan-C001084-Amdt-11.pdf', 'AuthorizationandOversightPlan'),
    ('BILLS-118CommitteeAuthorizationandOversightPlanih.pdf', 'CommitteeAuthorizationandOversightPlan'),
    ('BILLS-119pih-AuthorizationOversightPlan.pdf', 'AuthorizationOversightPlan'),
    ('BILLS-119OversightPlanih.pdf', 'OversightPlan'),
    ('Committee Authorization and Oversight Plan.pdf', 'Committee Authorization and Oversight Plan'),
    ('Committee Oversight Plan for the 119th Congress.pdf', 'Committee Oversight Plan'),
    ('Authorization and Oversight Planpdf.pdf', 'Authorization and Oversight Plan'),
])
def test_plan_phrase(engine, name, label):
    _, added = checked(engine, name)
    match, = [m for m in added if m['rule'] == 'oversight-plan-wording']
    assert match['fields'][0]['raw'] == label


@pytest.mark.parametrize('name,year', [
    ('BILLS-115pih-ViewsandEstimatesFY19.pdf', '19'),
    ('BILLS-116pih-ViewsandEstimatesFY2020.pdf', '2020'),
    ('BILLS-114pih-VAslegislativeproposalregardingFY16constructionprojects.pdf', '16'),
    ('BILLS-114hconres-BudgetFY2016.xml', '2016'),
    ('SummaryFY-24.pdf', '24'),
    ('SummaryFY_2025.pdf', '2025'),
    ('SummaryFY 2026.pdf', '2026'),
    ('SummaryFY0000.pdf', '0000'),
])
def test_visible_joined_fiscal_boundary(engine, name, year):
    _, added = checked(engine, name)
    match, = [m for m in added if m['rule'] == 'joined-fiscal-year']
    marker, value = match['fields']
    assert (marker['name'], marker['raw']) == ('fiscal_marker', 'FY')
    assert (value['name'], value['raw']) == ('fiscal_year_token', year)
    assert 'no calendar date' in value['note']
    assert ('century remains unspecified' in value['note']) == (len(year) == 2)


@pytest.mark.parametrize('name', [
    'interviews_and_estimates.pdf', 'Views and Estimating.pdf',
    'Views and Estimatesmanship.pdf', 'Oversight Planet.pdf',
    'AuthorizationandOversightPlanet.pdf', 'CommitteeOversightPlanter.pdf',
    'BILLS-119pih-ThisbillupdatesthethresholdsforSuspiciousActivityReportsSAR.pdf',
    'ShortPositionandShortActivityReporting.pdf',
    'testify2024.pdf', 'TESTIFY2024.pdf', 'SummaryFy2024.pdf', 'Summaryfy2024.pdf',
    'SummaryFY20245.pdf', 'SummaryFY2.pdf', 'SummaryFY202.pdf',
    'Topic%20Views and Estimates.pdf', 'Topic%20Oversight Plan.pdf', 'Topic%2aFY2024.pdf',
    'HHRG-119-IF00-Wstate-SummaryFY2024-20250318.pdf',
    'HHRG-119-IF00-Wstate-ViewsandEstimates-20250318.pdf',
    'HHRG-119-IF00-Wstate-AuthorizationandOversightPlan-20250318.pdf',
])
def test_unrelated_words_escapes_and_identifiers(engine, name):
    _, added = checked(engine, name)
    assert added == []


def test_existing_basic_plan_label_is_not_duplicated(engine):
    result, added = checked(engine, 'BILLS-119-OversightPlan-P000034-Amdt-74.pdf')
    assert not added
    labels = [field for match in result['observations'] for field in match['fields']
              if field['name'] == 'label' and field['raw'] == 'OversightPlan']
    assert len(labels) == 1


def test_notice_and_budget_phrase_both_remain(engine):
    result, _ = checked(engine, '03-04-20_views_and_estimate_notice.pdf')
    labels = {field['raw'] for match in result['observations'] for field in match['fields']
              if field['name'] == 'label'}
    assert labels == {'views_and_estimate_notice', 'views_and_estimate'}


def test_primary_congress_and_amendment_stay(engine):
    result, _ = checked(engine, 'BILLS-118-118thAuthorizationandOversightPlan-C001084-Amdt-11.pdf')
    fields = {(field['name'], field['raw']) for match in result['observations'] for field in match['fields']}
    assert {('congress', '118'), ('bioguide_token', 'C001084'), ('amendment_token', '11')} <= fields
    assert ('referenced_congress', '118') not in fields  # No Congress marker printed beside this ordinal.


def test_separate_conflicting_fiscal_tokens_are_not_reconciled(engine):
    result, added = checked(engine, 'BILLS-117-SC-AP-FY2022-Defense-DraftBillFY2023.pdf')
    match, = [m for m in added if m['rule'] == 'joined-fiscal-year']
    assert match['fields'][1]['raw'] == '2023'
    years = {(f['raw'], f['start'], f['end']) for m in result['observations']
             for f in m['fields'] if f['name'] == 'fiscal_year_token'}
    assert {value for value, _, _ in years} == {'2022', '2023'}
    assert len(years) == 2
