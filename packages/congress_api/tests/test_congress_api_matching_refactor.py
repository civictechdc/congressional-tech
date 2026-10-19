"""Date boundaries and primary committee selection used by inventory matching."""

import datetime as dt

import pytest

from congress_api.matching.gpo_committees import clean_rows
from congress_api.matching.recordings import MONTHS, title_dates


@pytest.mark.parametrize('month,name', list(enumerate(MONTHS, 1)))
def test_upload_title_month_names_and_abbreviations(month, name):
    expected = {dt.date(2024, month, 29)}
    assert title_dates(f'{name.title()} 29, 2024 Hearing') == expected
    assert title_dates(f'{name[:3].upper()}. 29, 2024 Hearing') == expected


def test_upload_dates_reject_invalid_days_and_keep_multiple_distinct_dates():
    assert title_dates('02/29/24; 2-29-2023; June 31, 2024; 12.31.2024; ſep 1, 2024') == {
        dt.date(2024, 2, 29), dt.date(2024, 12, 31),
    }


def test_primary_committee_survives_additional_and_invalid_codes():
    row = {
        'package_id': 'CHRG-119shrg99999', 'title': 'A hearing',
        'chamber': 'Senate', 'committee_name': '',
        'committee_code_gpo': 'ssap00', 'committee_code': 'ssap00',
        'committee_codes_gpo': 'ssju00;unusable;SSJU00',
    }
    clean_rows({row['package_id']: row})
    assert row['committee_code'] == 'ssap00'
    assert row['committee_codes'] == 'ssap00;ssju00'
    assert row['committee_codes_gpo'] == 'ssju00;unusable;SSJU00'
    before = dict(row)
    clean_rows({row['package_id']: row})
    assert row == before
