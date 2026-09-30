"""Source contexts disambiguate dates from local numbers and day ranges."""
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


def fields(result, name):
    return [f for m in result['observations'] for f in m['fields'] if f['name']==name]


@pytest.mark.parametrize('name', ['haynes-testimony-addendum-2-3-29-22',
                                  'haynes-testimony-addendum-2-3-29-22&download=1',
                                  'Haynes Testimony Addendum 2 3-29-22.pdf'])
def test_actual_numbered_addendum_keeps_complete_following_date(engine, name):
    result = checked(engine, name)
    assert {f['raw'] for f in fields(result, 'date_token')} == {'3-29-22'}
    assert fields(result, 'local_number_token')[0]['raw'] == '2'
    assert not fields(result, 'date_token')[0]['candidates']
    assert not fields(result, 'generic_identifier')


@pytest.mark.parametrize('name,date', [
    ('Haynes Testimony Addendum 3-29-22.pdf', '3-29-22'),
    ('Hartwig Testimony Addendum 7-22-21.pdf', '7-22-21'),
    ('powell_testimony_addendum_10-21-25.pdf', '10-21-25'),
])
def test_actual_date_only_addendum_does_not_invent_an_addendum_number(engine, name, date):
    result = checked(engine, name)
    assert {f['raw'] for f in fields(result, 'date_token')} == {date}
    assert not fields(result, 'local_number_token')


@pytest.mark.parametrize('name', ['Fraser Testimony Addendum 5-26-211.pdf',
                                  'Moynihan Testimony Addendum - 2020 Human Capital Management Report.pdf',
                                  'Addendum 2 2024-02-31.pdf'])
def test_nonmatching_addendum_text_is_not_repaired_or_given_a_number(engine, name):
    result = checked(engine, name)
    assert not fields(result, 'local_number_token')


@pytest.mark.parametrize('name,raw,candidates', [
    ('testimony_rainey_revised_1262022', '1262022', ['2022-01-26','2022-06-12','2022-12-06']),
    ('Smith Revised 20240229.pdf', '20240229', ['2024-02-29']),
    ('Smith Revision 022924.pdf', '022924', []),
    ('Smith Rev 2-29-2024.pdf', '2-29-2024', ['2024-02-29']),
])
def test_revision_wording_keeps_printed_date_instead_of_sequence_number(engine, name, raw, candidates):
    result = checked(engine, name)
    dates=fields(result,'date_token')+fields(result,'short_date_token')
    assert any(f['raw']==raw and f['candidates']==candidates for f in dates)
    assert not fields(result,'revision_number')
    assert any(s['reason'].startswith('Date follows revision wording') for s in result['suppressed'])


@pytest.mark.parametrize('name,number', [('Smith Revised 3.pdf','3'), ('Smith Version 123456.pdf','123456'),
                                       ('Smith V20240229.pdf','20240229')])
def test_explicit_small_or_uninterpreted_revision_numbers_remain_numbers(engine, name, number):
    result = checked(engine, name)
    assert number in [f['raw'] for f in fields(result, 'revision_number')]


@pytest.mark.parametrize('name,raw', [
    ('Results Of The Open Executive Session Of June 9-10, 2021.pdf','June 9-10, 2021'),
    ('open-executive-session-to-consider-the-nominations-of-lily-lawrence-batchelder-benjamin-harris-j-nellie-liang-and-jonathan-davidson-june-9-10-2021','june-9-10-2021'),
    ('Smith June 9–10, 2021.pdf','June 9–10, 2021'),
])
def test_same_month_range_retains_both_days_and_actual_year(engine, name, raw):
    result=checked(engine,name)
    interval,=fields(result,'date_range_token')
    assert interval['raw']==raw
    assert interval['candidates']==['2021-06-09/2021-06-10']
    assert [f['raw'] for f in fields(result,'start_day_token')]==['9']
    assert [f['raw'] for f in fields(result,'end_day_token')]==['10']
    assert [f['raw'] for f in fields(result,'year_token')]==['2021']
    assert not fields(result,'date_token')
    assert not fields(result,'generic_identifier')


@pytest.mark.parametrize('text', ['February 29-30, 2024', 'June 10-9, 2021', 'February 28-29, 2023'])
def test_invalid_range_retains_printed_components_without_calendar_candidate(engine,text):
    result=checked(engine,'Smith '+text+'.pdf')
    interval,=fields(result,'date_range_token')
    assert interval['raw']==text and not interval['candidates']
    assert 'Invalid' in interval['note']


def test_day_year_form_stays_a_single_date(engine):
    result=checked(engine,'Smith June 9 2021.pdf')
    assert not fields(result,'date_range_token')
    assert fields(result,'date_token')[0]['candidates']==['2021-06-09']
