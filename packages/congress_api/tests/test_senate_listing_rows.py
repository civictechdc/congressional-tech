"""Semantic event rows date their own link and keep displayed and encoded clocks apart."""
import datetime as dt
from pathlib import Path

from congress_api.acquisition import senate as records
from congress_api.models.senate import ListingColumns
from congress_api.parsers.senate import parse_listing_details, parse_listing_page

SOURCES = Path(__file__).parent / 'fixtures/source_models'
SITE = 'appropriations.senate.gov'
CAPITOL = (SOURCES / 'senate-listing-event-capitol-police.html').read_text()
CAPITOL_URL = ('https://www.appropriations.senate.gov/hearings/a-review-of-the-fiscal-year-2027-budget-requests'
               '-for-the-senate-sergeant-at-arms-and-united-states-capitol-police')
FORM = '/hearings?page={}'


def only(name, site):
    return next(iter(parse_listing_details((SOURCES / name).read_text(), site).values()))


def test_capitol_police_row_uses_its_own_day_not_the_row_above():
    days = {url: day for day, url, _ in parse_listing_page(CAPITOL, SITE)}
    assert days[CAPITOL_URL] == dt.date(2026, 4, 22)


def test_conflicting_clock_keeps_the_displayed_time_and_the_encoded_value():
    assert parse_listing_details(CAPITOL, SITE)[CAPITOL_URL] == {
        'room': 'Dirksen Senate Office Building 138', 'type': 'Subcommittee Hearing:', 'time': '03:00PM',
        'date_text': '04/22/26', 'encoded_start': '2026-04-22T03:00', 'time_evidence': 'displayed_conflicts_encoded'}


def test_matching_clock_is_recorded_as_a_match():
    details = parse_listing_details(CAPITOL, SITE).values()
    morning = next(row for row in details if row['date_text'] == '04/28/26')
    assert morning['time'] == '10:00AM' and morning['time_evidence'] == 'displayed_matches_encoded'


def test_date_only_row_never_selects_its_encoded_clock():
    row = only('senate-listing-event-date-only.html', 'finance.senate.gov')
    assert 'time' not in row
    assert row['encoded_start'] == '2023-03-23T10:00' and row['time_evidence'] == 'encoded_only_ambiguous'


def test_unencoded_row_keeps_its_visible_day_and_infers_nothing():
    page = (SOURCES / 'senate-listing-event-unencoded.html').read_text()
    assert [day for day, _, _ in parse_listing_page(page, 'finance.senate.gov')] == [dt.date(2019, 6, 11)]
    row = only('senate-listing-event-unencoded.html', 'finance.senate.gov')
    assert row['date_text'] == '06/11/19' and row['time_evidence'] == 'displayed_only'
    assert 'time' not in row and 'encoded_start' not in row


def test_root_slug_row_has_columns_but_stays_out_of_discovery():
    # HEARING_LINK decides discovery and lives in the byte-hashed senate_page.py: an open item.
    page = (SOURCES / 'senate-listing-event-root-slug.html').read_text()
    assert parse_listing_page(page, 'budget.senate.gov') == []
    assert only('senate-listing-event-root-slug.html', 'budget.senate.gov')['date_text'] == '09.23.20'


def test_old_saved_columns_still_validate():
    assert ListingColumns.model_validate({'room': 'S-116', 'time': '10:00 AM'}).source_dict() == {'room': 'S-116', 'time': '10:00 AM'}


def pages(*bodies):
    fetched = []
    def get(url):
        fetched.append(url)
        return bodies[len(fetched) - 1] if len(fetched) <= len(bodies) else ''
    return get, fetched


SAVED = {'form': FORM, 'from_0': False, 'listings': {}, 'listing_details': {}}


def test_cutoff_drops_a_row_that_proximity_would_have_dated_newer():
    # The rows show 04/28, 04/22, 04/22. With proximity the middle row read 04/28 and stayed.
    get, fetched = pages(CAPITOL)
    kept, route = records.listed(SITE, get, saved=SAVED, since=dt.date(2026, 4, 25))
    assert [day for day, _, _ in kept] == [dt.date(2026, 4, 28)]
    assert CAPITOL_URL not in {url for _, url, _ in kept}
    assert CAPITOL_URL not in route['listing_details']
    assert len(fetched) == 2  # the newest row is in scope, so the next page is read and is empty


def test_pagination_stops_when_a_whole_page_is_older_than_the_cutoff():
    get, fetched = pages(CAPITOL, CAPITOL)
    kept, _ = records.listed(SITE, get, saved=SAVED, since=dt.date(2026, 5, 1))
    assert kept == [] and len(fetched) == 1
