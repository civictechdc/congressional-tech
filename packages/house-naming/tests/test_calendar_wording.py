"""Partial dates preserve source precision and never invent calendar days."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


def checked(engine, name):
    result = engine.extract(name)
    assert all(result[k] == value for k, value in engine.parse(name).items())
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in (*result['observations'], *result['suppressed']):
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']
            assert m['start'] <= f['start'] <= f['end'] <= m['end']
    return result


def matches(result, rule):
    return [m for m in result['observations'] if m['rule'] == rule]


@pytest.mark.parametrize('name,raw,month,year,candidate', [
    ('Paul Smith CV April 2021.pdf', 'April 2021', 'April', '2021', '2021-04'),
    ('AELP_Bill_McGee_Written_Testimony_March2023_PDF.pdf', 'March2023', 'March', '2023', '2023-03'),
    ('Captain Casey Murray Testimony Senate CST Feb2023 .pdf', 'Feb2023', 'Feb', '2023', '2023-02'),
    ('ContemptReport.HunterBiden.CommitteeOversightAccount.Jan2024.FINAL_.pdf', 'Jan2024', 'Jan', '2024', '2024-01'),
    ('Robert Pearce CST Hearing Testimony_final3 (Mar. 2023).pdf', 'Mar. 2023', 'Mar', '2023', '2023-03'),
    ('July 2021 TR Written Senate Testimony final.pdf', 'July 2021', 'July', '2021', '2021-07'),
    ('lindsay-owens-testimony-april-2022&download=1', 'april-2022', 'april', '2022', '2022-04'),
    ('paul-smith-cv-april-2021pdf', 'april-2021', 'april', '2021', '2021-04'),
    ('Testimony Sept_2023.pdf', 'Sept_2023', 'Sept', '2023', '2023-09'),
    ('Testimony February 0000.pdf', 'February 0000', 'February', '0000', None),
])
def test_month_year_precision(engine, name, raw, month, year, candidate):
    result = checked(engine, name)
    match, = matches(result, 'named-month-year')
    fields = {f['name']: f for f in match['fields']}
    assert {k: f['raw'] for k, f in fields.items()} == {
        'month_token': month, 'year_token': year, 'month_year_token': raw,
    }
    assert fields['month_year_token']['candidates'] == ([candidate] if candidate else [])
    assert 'day' in fields['month_year_token']['note']
    assert all(f['code'] is None and f['context'] is None for f in fields.values())
    assert 'date_token' not in fields and 'day_token' not in fields


@pytest.mark.parametrize('name,marker,year', [
    ('-a-review-of-the-fiscal-year-2023-presidents-budget-for-the-us-forest-service', 'fiscal-year', '2023'),
    ('03 22 23 -- American Diplomacy - Fiscal Year 2024 Budget Request.pdf', 'Fiscal Year', '2024'),
    ('Budget_Fiscal_Year_2025.pdf', 'Fiscal_Year', '2025'),
    ('FiscalYear2023CommerceJusticeScienceAppropriationsBill.pdf', 'FiscalYear', '2023'),
    ('legislative-branch-fiscal-year-24-appropriations-bill-summary&download=1', 'fiscal-year', '24'),
])
def test_written_fiscal_year(engine, name, marker, year):
    match, = matches(checked(engine, name), 'written-fiscal-year')
    fields = {f['name']: f for f in match['fields']}
    assert {k: f['raw'] for k, f in fields.items()} == {
        'fiscal_marker': marker, 'fiscal_year_token': year,
    }
    assert fields['fiscal_year_token']['candidates'] == []
    assert 'calendar date' in fields['fiscal_year_token']['note']
    if len(year) == 2:
        assert 'century' in fields['fiscal_year_token']['note']


def test_all_repeated_years_are_retained(engine):
    result = checked(engine, 'fiscal-year-2020-budget-for-veterans-programs-and-fiscal-year-2021-advance-appropriations-request')
    assert [f['raw'] for m in matches(result, 'written-fiscal-year')
            for f in m['fields'] if f['name'] == 'fiscal_year_token'] == ['2020', '2021']
    result = checked(engine, 'Exhibit B3_Mudge moleskine + phone notes Dec 2020 Feb 2022_redacted_sanitized_opt.pdf')
    assert [f['candidates'] for m in matches(result, 'named-month-year')
            for f in m['fields'] if f['name'] == 'month_year_token'] == [['2020-12'], ['2022-02']]


def test_appropriation_slot_and_repeated_written_year_remain_distinct(engine):
    name = 'BILLS-117-SC-AP-FY2023-CJS-FiscalYear2023CommerceJusticeScienceandRelatedAgenciesAppropriationsBill.pdf'
    result = checked(engine, name)
    match, = matches(result, 'written-fiscal-year')
    assert [f['raw'] for f in match['fields']] == ['FiscalYear', '2023']
    assert any(f['name'] == 'fiscal_marker' and f['raw'] == 'FY'
               for m in result['observations'] for f in m['fields'])


@pytest.mark.parametrize('name', [
    '(CLEARED)_SASC_Posture_Statement_PB22_FINAL_26_Apr_2021_1715.pdf',
    '02JUN2020.pdf', '31 February 2021.pdf', 'April 1 2021.pdf',
    'April 20231.pdf', 'April 202.pdf', 'April 21.pdf', 'Marching2023.pdf',
    'PreMarch2023.pdf', 'Kurilla_SASC_Posture_Final_141200March2023.pdf',
    'HHRG-119-IF00-Wstate-April2021-20250318.pdf',
    'HHRG-119-IF00-Wstate-FiscalYear2024-20250318.pdf',
    'FiscalYear20234.pdf', 'FiscalYear202.pdf', 'PreFiscalYear2024.pdf',
])
def test_fragments_and_assigned_ids_are_not_partial_dates(engine, name):
    result = checked(engine, name)
    assert not matches(result, 'named-month-year')
    assert not matches(result, 'written-fiscal-year')


def test_original_name_and_number_assumptions_remain_inspectable(engine):
    result = checked(engine, 'Paul Smith CV April 2021.pdf')
    assert matches(result, 'named-month-year')
    assert any(f['name'] == 'generic_identifier' and f['raw'] == '2021'
               for m in result['observations'] for f in m['fields'])
    assert any(f['name'] == 'name_token' and f['raw'] == 'Paul Smith CV April'
               for m in result['observations'] for f in m['fields'])
