"""Semantic event rows date their own link and keep displayed and encoded clocks apart."""
import datetime as dt
from pathlib import Path

import pytest

from congress_api.acquisition import senate as records
from congress_api.models.senate import ListingColumns
from congress_api.parsers.senate import displayed_clock, parse_listing_details, parse_listing_page
from congress_api.parsers.senate_page import event_details

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


def test_root_slug_event_row_is_discovered_through_hearing_link():
    page = (SOURCES / 'senate-listing-event-root-slug.html').read_text()
    (day, url, _), = parse_listing_page(page, 'budget.senate.gov')
    assert day == dt.date(2020, 9, 23) and url == 'https://www.budget.senate.gov/-hearing-on-cbos-updated-budget-outlook'


def test_a_root_link_without_the_event_url_class_is_not_a_hearing():
    for classes in ('url-nav', 'nav-url', 'urls', 'my_url'):
        assert parse_listing_page(f'<a href="/about" class="{classes}">About</a> 04/22/26', SITE) == []
    for classes in ('url', 'url summary', 'pull-left url'):
        assert len(parse_listing_page(f'<a href="/a-hearing" class="{classes}">Hearing</a> 04/22/26', SITE)) == 1
    assert parse_listing_page('<a href="/about" class="nav">About</a> 04/22/26', SITE) == []
    assert parse_listing_page('<a href="/about">About</a> 04/22/26', SITE) == []


def test_root_slug_hearing_page_becomes_an_event_with_its_displayed_date():
    # Trimmed real page; see the fixture's provenance comment.
    url = 'https://www.appropriations.senate.gov/a-review-of-preparations-for-the-fifa-world-cup-2026'
    event = event_details((SOURCES / 'senate-root-slug-hearing.html').read_text(), url)
    assert (event['title'], event['date'], event['type']) == ('A Review of Preparations for the FIFA World Cup 2026', '2026-04-15', 'Hearing')


def test_root_page_without_the_hearing_template_is_not_an_event():
    url = 'https://www.appropriations.senate.gov/about'
    assert event_details('<h1 class="main_page_title">About</h1><span class="date">Date: April 15, 2026</span>', url) is None


def test_hearings_page_with_the_template_is_unchanged():
    page = '<h1 class="main_page_title">T</h1><p class="hearing-meta row"><span class="date col-md-12">Date: April 15, 2026</span></p>'
    assert event_details(page, 'https://www.appropriations.senate.gov/hearings/x') is None


def test_row_dated_by_a_table_cell_keeps_the_table_branch():
    # Synthetic shape from review: a vevent class without <time>.
    page = ('<table><tr><td class="recordListDate">04/28/26 10:00 AM</td><td><a href="/hearings/first">First</a></td></tr>'
            '<tr class="vevent"><td class="recordListDate">04/22/26 03:00 PM</td><td><a href="/hearings/second">Second</a></td></tr></table>')
    days = {url.rsplit('/', 1)[1]: day for day, url, _ in parse_listing_page(page, SITE)}
    assert days['second'] == dt.date(2026, 4, 22)
    assert parse_listing_details(page, SITE)['https://www.appropriations.senate.gov/hearings/second']['time'] == '03:00 PM'


def test_wrapper_vevent_does_not_give_every_link_the_first_date():
    page = ('<div class="vevent"><p><a href="/hearings/first">First</a> <time>04/28/26</time></p>'
            '<p><a href="/hearings/second">Second</a> <time>04/22/26</time></p></div>')
    assert 'date_text' not in parse_listing_details(page, SITE).get('https://www.appropriations.senate.gov/hearings/second', {})


def test_impossible_clock_is_not_a_clock():
    assert displayed_clock('10:75 AM') is None and displayed_clock('13:00 PM') is None
    assert displayed_clock('12:30 AM') == (0, 30) and displayed_clock('12:30 PM') == (12, 30)
    page = '<table><tr class="vevent"><td><a class="url" href="/hearings/x">X</a><time datetime="2026-04-22T10:75">04/22/26 10:75 AM</time></td></tr></table>'
    assert parse_listing_details(page, SITE)['https://www.appropriations.senate.gov/hearings/x']['time_evidence'] == 'encoded_only_ambiguous'


@pytest.mark.parametrize('fixture,site', [
    ('senate-listing-event-capitol-police.html', SITE), ('senate-listing-event-date-only.html', 'finance.senate.gov'),
])
def test_days_agree_with_mf2py_a_different_parser_family(fixture, site):
    import mf2py
    page = (SOURCES / fixture).read_text()
    events = [item for item in mf2py.parse(doc=page, url=f'https://www.{site}/hearings')['items'] if 'h-event' in item['type']]
    declared = {item['properties']['url'][0]: item['properties']['start'][0][:10] for item in events}
    assert declared and {url: str(day) for day, url, _ in parse_listing_page(page, site)} == declared


def test_old_saved_columns_still_validate():
    assert ListingColumns.model_validate({'room': 'S-116', 'time': '10:00 AM'}).source_dict() == {'room': 'S-116', 'time': '10:00 AM'}


def pages(*bodies):
    fetched = []
    def get(url):
        fetched.append(url)
        return bodies[len(fetched) - 1] if len(fetched) <= len(bodies) else ''
    return get, fetched


# As saved routes are: route omits listing_details when a site has none.
SAVED = {'form': FORM, 'from_0': False, 'listings': {}}


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


def test_route_saved_without_listing_details_does_not_raise():
    # Every form site in the retained snapshots has this shape.
    get, _ = pages('')
    assert records.listed(SITE, get, saved={**SAVED, 'listing_details': None}, since=dt.date(2026, 1, 1))[0] == []
    get, _ = pages('')
    assert records.listed(SITE, get, saved=SAVED, since=dt.date(2026, 1, 1))[0] == []


def test_intelligence_discovers_only_dated_open_hearing_cards_with_capturable_links():
    from congress_api.acquisition.capture_scheduler import CapturePolicy

    site = 'intelligence.senate.gov'
    origin = f'https://www.{site}'
    listing = origin + '/category/hearings/open-hearings/'
    link = origin + '/2026/03/17/open-hearing-worldwide-threats-2/'
    # The retained listing fa9a52fb… displays March 18 on the exact March 17 permalink.
    card = (
        '<article class="et_pb_post category-hearings category-open-hearings">'
        f'<h3 class="entry-title"><a href="{link}">Open Hearing: Worldwide Threats</a></h3>'
        '<p class="post-meta"><span class="date-display display">Mar 18, 2026 10:00am</span></p></article>'
    )
    unrelated = card.replace('category-open-hearings', 'category-closed-meetings')
    foreign_link = card.replace(origin, 'https://other.example')
    undated = card.replace('Mar 18, 2026 10:00am', '')
    get, fetched = pages(card + unrelated + foreign_link + undated)
    kept, route = records.listed(site, get, saved=SAVED, since=dt.date(2026, 3, 18))
    assert kept == [(dt.date(2026, 3, 18), link, 'Open Hearing: Worldwide Threats')]
    assert route['form'] == '/category/hearings/open-hearings/'
    assert fetched == [listing, listing + 'page/2/?et_blog']

    scope = Path(__file__).parents[3] / 'model/registries/capture-scope.json'
    policy = CapturePolicy(scope)
    assert [policy.pattern_family(url) for url in [*fetched, link]] == ['senate/pages'] * 3
    assert policy.pattern_family(origin + '/2026/05/20/intelligence-authorization-act/') is None
    assert policy.pattern_family(origin + '/2026/06/10/closed-briefing-intelligence-matters-74/') is None


def test_pins_match_the_current_parser_sources():
    import json
    from congress_api.lake import appearance_records, meeting_records, readings
    pins = json.loads((Path(__file__).parents[3] / 'model/jobs/publish-model.json').read_text())['parser_versions']
    assert {name: readings.current_version(name) for name in ('html', 'xml', 'json', 'sniff')} == {name: pins[name] for name in ('html', 'xml', 'json', 'sniff')}
    assert meeting_records.current_versions() == pins['meeting_records']
    assert appearance_records.current_versions() == pins['appearance_records']
