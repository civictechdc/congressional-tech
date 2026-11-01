"""Explicit numeric references own their digits before generic date scans."""
import pytest

from house_naming import Engine


@pytest.fixture(scope='module')
def engine():
    return Engine()


@pytest.mark.parametrize('reference,field,number', [
    ('HR111111', 'measure_number', '111111'),
    ('H.R. 12345', 'measure_number', '12345'),
    ('S.Res.20250318', 'measure_number', '20250318'),
    ('Amendment111111', 'amendment_token', '111111'),
    ('Amdt-12345', 'amendment_token', '12345'),
    ('Exhibit 12345', 'item_token', '12345'),
    ('Agenda Item 111111', 'item_token', '111111'),
    ('Attachment 20250318', 'item_token', '20250318'),
    ('x-SD111111', 'document_identifier', '111111'),
    ('x-QFR12345', 'document_identifier', '12345'),
    ('x-Vote20250318', 'document_identifier', '20250318'),
    ('S.Hrg.119-12345', 'citation_number', '12345'),
])
@pytest.mark.parametrize('suffix', ['', ' Hearing-2025-03-19'])
def test_reference_wins_without_hiding_adjacent_date(engine, reference, field, number, suffix):
    name = reference + suffix + '.pdf'
    result = engine.extract(name)
    fields = [f for m in result['observations'] for f in m['fields']]
    identifier = next(f for f in fields if f['name'] == field and f['raw'] == number)
    dates = [f for f in fields if f['name'] in {'date_token', 'short_date_token'}]
    assert not any(f['start'] < identifier['end'] and f['end'] > identifier['start'] for f in dates)
    assert bool(dates) == bool(suffix)
    if suffix:
        assert any(f['candidates'] == ['2025-03-19'] for f in dates)
    assert any(s['start'] < identifier['end'] and s['end'] > identifier['start']
               and s['reason'] == 'Overlaps a structured or already assigned token.'
               for s in result['suppressed'])
    assert ''.join(p['raw'] for p in result['pieces']) == name
    for m in (*result['observations'], *result['suppressed']):
        for f in m['fields']:
            assert name[f['start']:f['end']] == f['raw']


@pytest.mark.parametrize('subject', ['HR111111', 'Amdt111111', 'SD111111', 'Exhibit12345'])
def test_structured_witness_identifier_remains_opaque(engine, subject):
    result = engine.extract(f'HHRG-119-IF00-Wstate-{subject}-20250318.pdf')
    assert not any(m['rule'] in {'measure-reference', 'amendment-reference', 'exhibit-reference', 'document-suffix'}
                   for m in result['observations'])


def test_reference_and_complete_uuid_remain_independent(engine):
    result = engine.extract('HR111111-11111111-1111-4111-8111-111111111111.pdf')
    fields = [f for m in result['observations'] for f in m['fields']]
    assert any(f['name'] == 'measure_number' and f['raw'] == '111111' for f in fields)
    assert any(f['name'] == 'opaque_uuid' for f in fields)
    assert not any(f['name'] in {'date_token', 'short_date_token'} for f in fields)


@pytest.mark.parametrize('name,raw', [
    ('Burman Statement - Attachment 3-27-19 SENR Cmte WP Subcmte Hrg.pdf', '3-27-19'),
    ('Cecere Testimony Attachment 9-22-22.pdf', '9-22-22'),
    ('Attachment 06.12.2019.pdf', '06.12.2019'),
    ('Hershman_APQ s_10-29-19.pdf', '10-29-19'),
])
def test_reference_cannot_cut_a_complete_separated_date(engine, name, raw):
    result = engine.extract(name)
    assert any(f['name'] == 'date_token' and f['raw'] == raw
               for m in result['observations'] for f in m['fields'])
    assert any(s['reason'] == 'Reference would consume only a prefix of a complete separated date.'
               for s in result['suppressed'])


@pytest.mark.parametrize('name,token,number,date_token,candidates,suppressed_date', [
    ('hearing_memo_--_leg_hrg_on_h.r._2199_05.23.17.pdf', 'h.r.', '2199', '05.23.17', [], '2199_05.23'),
    ('hearing_memo_--_leg_hrg_on_hr_2167_06.23.16.pdf', 'hr', '2167', '06.23.16', [], '2167_06.23'),
    ('hearing_memo_--_leg_hrg_on_h.r._1234_05.23.17.pdf', 'h.r.', '1234', '05.23.17', [], None),
    ('hearing_memo_--_leg_hrg_on_hr_1234_06.23.16.pdf', 'hr', '1234', '06.23.16', [], None),
    ('hearing_memo_--_leg_hrg_on_h.r._2199_05.23.2017.pdf', 'h.r.', '2199', '05.23.2017', ['2017-05-23'], '2199_05.23'),
    ('hearing_memo_--_leg_hrg_on_hr_2167_06.23.2016.pdf', 'hr', '2167', '06.23.2016', ['2016-06-23'], '2167_06.23'),
    ('Bill-Text-H.R.1786-9-11-Victims-Compensation-Fund-2015-6-11_0.pdf', 'H.R.', '1786', '2015-6-11', ['2015-06-11'], '1786-9-11'),
    ('Bill-Text-H.R.1789-9-11-Victims-Compensation-Fund-2015-6-11_0.pdf', 'H.R.', '1789', '2015-6-11', ['2015-06-11'], '1789-9-11'),
    ('101521_hr_1786_9_11_immigrant_worker_freedom_act.pdf', 'hr', '1786', '101521', [], '1786_9_11'),
    ('H.R. 5342_2025-12-03_Hearing.pdf', 'H.R.', '5342', '2025-12-03', ['2025-12-03'], None),
    ('H.R. 2024_2024-05-10.pdf', 'H.R.', '2024', '2024-05-10', ['2024-05-10'], None),
])
def test_explicit_bill_reference_preceding_separate_date_retains_span(
    engine, name, token, number, date_token, candidates, suppressed_date
):
    result = engine.extract(name)
    metadata = result['metadata']
    assert metadata['measure_token'] == [token]
    assert metadata['measure_token_code'] == ['hr']
    assert metadata['measure_number'] == [number]
    assert metadata['measure_references'] == ['hr' + number]
    assert metadata['date_token'] == [date_token]
    assert metadata.get('date_token_candidates', []) == candidates
    assert not any(c.startswith(('2199-', '2167-', '1786-', '1789-')) for c in metadata.get('date_token_candidates', []))
    if not candidates:
        date_fields = [f for m in result['observations'] for f in m['fields'] if f['name'] == 'date_token']
        assert date_fields and all(
            f['candidates'] == [] and 'century and month/day/year order remain unspecified' in f['note']
            for f in date_fields
        )
    if suppressed_date is not None:
        assert any(s['rule'] == 'date-separated' and s['raw'] == suppressed_date
                   and s['reason'] == 'Overlaps a structured or already assigned token.'
                   for s in result['suppressed'])


def test_recovered_bill_reference_and_literal_future_date_preserve_producer_boundaries(engine):
    from datetime import date
    from congress_api.lake.filenames import read_filename

    short = read_filename('hearing_memo_--_leg_hrg_on_h.r._2199_05.23.17.pdf', '', catalog_version='v', parser=engine)
    assert short['date_token'] == '05.23.17' and short['filename_date'] is None
    assert short['measure_number'] == '2199' and short['congress'] is None and short['measure_keys'] == []

    with_congress = read_filename(
        'HHRG-115-II10-hearing_memo_--_leg_hrg_on_h.r._2199_05.23.17.pdf', '', catalog_version='v', parser=engine
    )
    assert with_congress['congress'] == 115 and with_congress['measure_keys'] == ['115-hr-2199']
    assert with_congress['date_token'] == '05.23.17' and with_congress['filename_date'] is None

    for victims_name, expected_bill in [
        ('Bill-Text-H.R.1786-9-11-Victims-Compensation-Fund-2015-6-11_0.pdf', '1786'),
        ('Bill-Text-H.R.1789-9-11-Victims-Compensation-Fund-2015-6-11_0.pdf', '1789'),
    ]:
        victims_fund = read_filename(victims_name, '', catalog_version='v', parser=engine)
        assert victims_fund['measure_number'] == expected_bill
        assert victims_fund['date_token'] == '2015-6-11'
        assert victims_fund['filename_date'] == date(2015, 6, 11)

    for bill_date_name, expected_bill, expected_date in [
        ('H.R. 5342_2025-12-03_Hearing.pdf', '5342', date(2025, 12, 3)),
        ('H.R. 2024_2024-05-10.pdf', '2024', date(2024, 5, 10)),
    ]:
        parsed = read_filename(bill_date_name, '', catalog_version='v', parser=engine)
        assert parsed['measure_number'] == expected_bill
        assert parsed['filename_date'] == expected_date

    for iso_date_name, expected_date in [
        ('Dem-Memo-HE Markup of H.R. __2018-06-27.pdf', date(2018, 6, 27)),
        ('Dem-Memo-HE Markup of H.R. __2018_06_27.pdf', date(2018, 6, 27)),
        (
            'Dem-Memo-HE-Hrg-on-Better-Data-and-Better-Outcomes-Reducing-Maternal-Mortality-in-the-U.S.-2018-09-27.pdf',
            date(2018, 9, 27),
        ),
        (
            '20180927_1000_2172_Hrg_on_Better_Data_Reducing_Maternal_Mortality_in_the_U.S._2018_09_27.pdf',
            date(2018, 9, 27),
        ),
        ('H.R. 2018-06-27 hearing 07.01.18.pdf', date(2018, 6, 27)),
        ('H.R. 2018_06_27 hearing 07.01.18.pdf', date(2018, 6, 27)),
    ]:
        extracted = engine.extract(iso_date_name)
        assert 'measure_references' not in extracted['metadata']
        parsed = read_filename(iso_date_name, '', catalog_version='v', parser=engine)
        assert parsed['measure_number'] is None
        assert parsed['filename_date'] == expected_date

    partial_after_bill = engine.extract('hr_2199_05.23.pdf')
    assert partial_after_bill['metadata']['measure_token'] == ['hr']
    assert partial_after_bill['metadata']['measure_number'] == ['2199']
    assert partial_after_bill['metadata']['measure_references'] == ['hr2199']
    assert 'date_token' not in partial_after_bill['metadata']
    assert 'date_token_candidates' not in partial_after_bill['metadata']
    assert any(
        s['rule'] == 'date-separated'
        and s['raw'] == '2199_05.23'
        and s['reason'] == 'Overlaps a structured or already assigned token.'
        for s in partial_after_bill['suppressed']
    )
    partial_row = read_filename('hr_2199_05.23.pdf', '', catalog_version='v', parser=engine)
    assert partial_row['measure_number'] == '2199' and partial_row['congress'] is None and partial_row['measure_keys'] == []
    assert partial_row['date_token'] is None and partial_row['filename_date'] is None

    literal_future = engine.extract('FDA PAHPA testimony May 4 2303 HELP1.pdf')
    assert literal_future['metadata']['date_token'] == ['May 4 2303']
    assert literal_future['metadata']['date_token_candidates'] == ['2303-05-04']


