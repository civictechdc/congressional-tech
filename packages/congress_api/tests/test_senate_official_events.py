"""Actual committee layouts retain witnesses, attachment evidence and event identity."""
import json
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from committee_meeting.common import Ref
from committee_meeting.meetings import Meeting
from congress_api.acquisition import senate as records
from congress_api.adapters.common import AdapterContext
from congress_api.adapters.senate import official_events
from congress_api.adapters.senate import records as adapt
from congress_api.matching.senate_corrections import DATE_CORRECTIONS
from congress_api.models.senate import normalize_senate_state as records_normalize
from congress_api.parsers.senate import parsed as records_parsed
from congress_api.parsers.senate_page import event_details, witnesses
from congress_api.retention.tables import read_state as records_read_state
from congress_api.retention.tables import write_state as records_write_state
from congress_api.transport import http as records_http

FIXTURES = Path(__file__).parent / 'fixtures/senate_official'
NOW = datetime(2026, 9, 28, tzinfo=UTC)
URLS = {
    'indian-2026-08-04': 'https://www.indian.senate.gov/hearings/roundtable-titled-tracking-prediction-markets-exponential-growth-tribal-implications-and-beyond/',
    'drug-caucus-2026-06-24': 'https://www.drugcaucus.senate.gov/hearings/beyond-our-shores-the-global-reach-of-mexican-drug-cartels-and-risks-to-u-s-national-security/',
    'drug-field-2022': 'https://www.drugcaucus.senate.gov/hearings/u-s-senate-drug-caucus-to-hold-field-hearing-in-des-moines/',
    'drug-market-2022': next(iter(DATE_CORRECTIONS)),
    'drug-2011': 'https://www.drugcaucus.senate.gov/hearings/senate-caucus-on-international-narcotics-control-hearing-on-dangerous-synthetic-drugs/',
    'indian-2011': 'https://www.indian.senate.gov/hearings/business-meeting-consider-s-675-s-676/',
    'indian-housing-2026': 'https://www.indian.senate.gov/hearings/roundtable-to-discuss-how-native-hawaiian-serving-stakeholders-are-using-innovative-approaches-partnerships-and-advocacy-to-build-housing-supply-with-federal-and-state-funds/',
    'indian-nagpra-2026': 'https://www.indian.senate.gov/hearings/roundtable-to-discuss-advancing-the-promise-of-the-native-american-graves-protection-and-repatriation-act-and-to-identify-ways-congress-can-improve-its-implementation-for-the-native-hawaiian-community/',
}


def fixture(name):
    return (FIXTURES / (name + '.html')).read_text()


def context():
    return AdapterContext(now=NOW, input_id='senate-input', provider='senate.committees', ids=lambda kind, key: kind + ':' + key)


def state_for(name, **changes):
    url = URLS[name]
    page = {**records_parsed(fixture(name), url), 'events': [], **changes}
    host = 'indian.senate.gov' if name.startswith('indian') else 'drugcaucus.senate.gov'
    return json.loads(json.dumps({host: {'listings': {url: [page['event']['date'], page['event']['title']]}, 'pages': {url: page}}}))


def test_jet_h4_names_and_paragraph_roles_are_retained():
    indian = witnesses(fixture('indian-2026-08-04'), URLS['indian-2026-08-04'])
    assert len(indian) == 5
    assert indian[0]['name'] == 'Mark Macarro'
    assert indian[0]['position'] == 'President'
    assert 'National Congress of American Indians' in indian[0]['organization']
    drug = witnesses(fixture('drug-caucus-2026-06-24'), URLS['drug-caucus-2026-06-24'])
    assert len(drug) == 3
    assert drug[0]['name'] == 'Chris Urben'
    assert drug[0]['position'] == 'Ret. Assistant Special Agent in Charge, DEA'
    assert all('DOWNLOAD' not in witness['organization'] for witness in drug)
    assert not any('Cornyn' in witness['name'] for witness in drug)


@pytest.mark.parametrize('name,day,kind,congress', [
    ('drug-field-2022', '2022-10-27', 'field_hearing', 117),
    ('indian-housing-2026', '2026-08-26', 'roundtable', 119),
    ('indian-nagpra-2026', '2026-08-27', 'roundtable', 119),
    ('drug-2011', '2011-04-06', 'hearing', 112),
    ('indian-2011', '2011-04-07', 'business', 112),
])
def test_unmatched_official_event_is_admitted_without_inventing_congress_id(name, day, kind, congress):
    state = state_for(name)
    official, = official_events(state)
    assert official['congress'] == congress
    terms = {(congress, official['committee_code']): Ref(kind='committee_term', id='term')}
    rows = list(adapt(state, context(), meetings={}, committee_terms=terms))
    meeting, = [row for row in rows if row.kind == 'meeting']
    occurrence, = [row for row in rows if row.kind == 'occurrence']
    assert meeting.meeting_type == kind and meeting.congress == congress
    assert meeting.identifiers[0].scheme == 'senate.committee:page'
    assert meeting.identifiers[0].value == URLS[name]
    assert occurrence.scheduled_start.date.isoformat() == day
    assert occurrence.status == 'unknown'  # Passage of time does not prove it occurred.
    appearances = {row.id for row in rows if row.kind == 'appearance' and row.meeting.id == meeting.id}
    assert all(row.subject.id == meeting.id or row.subject.id in appearances for row in rows if row.kind == 'material_link')
    assert len([row for row in rows if row.kind == 'appearance']) == (0 if name == 'indian-2011' else 4 if name == 'drug-2011' else 5)
    # Changing the input snapshot/date cannot rename the proceeding.
    other = context(); other.input_id = 'next-refresh'
    replay, = [row for row in adapt(state, other, meetings={}, committee_terms=terms) if row.kind == 'meeting']
    assert replay.id == meeting.id


def test_roundtable_retains_competing_native_hearing_and_existing_identity():
    ctx = context()
    native_source = ctx.source('native', {'type': 'Hearing'})
    original = Meeting(id='existing', meeting_type='hearing', provenance=ctx.evidence(native_source))
    state = state_for('indian-2026-08-04', events=['900'])
    rows = list(adapt(state, ctx, meetings={(119, 'senate', '900'): Ref(kind='meeting', id='existing')}, meeting_records={'existing': original}))
    meeting, = [row for row in rows if row.kind == 'meeting']
    assert meeting.id == 'existing' and meeting.meeting_type == 'roundtable'
    assert meeting.field_evidence[0].alternatives[0].value == 'hearing'
    assert meeting.field_evidence[0].alternatives[0].provenance == original.provenance
    assert not [row for row in rows if row.kind == 'occurrence']


def test_known_date_correction_preserves_page_assertion_and_cites_transcript():
    state = state_for('drug-market-2022')
    rows = list(adapt(state, context(), meetings={}, committee_terms={(117, 'scnc00'): Ref(kind='committee_term', id='term')}))
    occurrence, = [row for row in rows if row.kind == 'occurrence']
    assert occurrence.scheduled_start.date == date(2022, 3, 2)
    assert occurrence.field_evidence[0].alternatives[0].value['date'] == '2022-03-04'
    assert any(row.kind == 'source_record' and row.url == DATE_CORRECTIONS[URLS['drug-market-2022']]['source_url'] for row in rows)
    assert state['drugcaucus.senate.gov']['pages'][URLS['drug-market-2022']]['event']['date'] == '2022-03-04'


def test_ambiguous_saved_event_does_not_become_an_extra_official_meeting():
    state = state_for('indian-housing-2026', events=['12'])
    lookup = {(118, 'senate', '12'): Ref(kind='meeting', id='old'), (119, 'senate', '12'): Ref(kind='meeting', id='new')}
    rows = list(adapt(state, context(), meetings=lookup, committee_terms={(119, 'slia00'): Ref(kind='committee_term', id='term')}))
    assert not any(row.kind in ('meeting', 'occurrence', 'appearance') for row in rows)


def test_publication_dates_and_unrecognized_dates_do_not_create_events():
    url = URLS['indian-2011']
    for source in ('<h1>Meeting</h1><p>April 7, 2011</p>', '<h1>Meeting</h1><meta name="datePublished" content="2011-04-07">'):
        assert event_details(source, url) is None
    assert event_details(fixture('indian-2011'), 'https://example.org/hearings/fake') is None


def test_explicit_attachment_follow_retains_original_url_label_and_pdf(monkeypatch):
    url = URLS['drug-caucus-2026-06-24']
    attachment = 'https://www.drugcaucus.senate.gov/media-center/files/chris-urben-testimony/'
    # One actual witness excerpt is enough to check the bounded resolver.
    html = fixture('drug-caucus-2026-06-24')
    html = html[:html.index('Michael Brown')]
    calls = []
    def get(_session, target, **kwargs):
        calls.append(target)
        return SimpleNamespace(status_code=200, content=(html if target == url else fixture('drug-attachment')).encode())
    monkeypatch.setattr(records_http, 'get_with_retry', get)
    page, _activity = records.fetch_page(url, {}, date(2026, 9, 28))
    assert calls == [url, attachment]
    assert page['document_labels'][attachment] == 'DOWNLOAD TESTIMONY'
    assert len(page['attachments'][attachment]) == 1
    pdf = page['attachments'][attachment][0]['url']
    assert pdf.endswith('Testimony-06_24_2026-Chris-Urben-1-1.pdf')
    state = json.loads(json.dumps({'drugcaucus.senate.gov': {'pages': {url: page}}}))
    rows = list(adapt(state, context(), meetings={}, committee_terms={(119, 'scnc00'): Ref(kind='committee_term', id='term')}))
    representations = [row for row in rows if row.kind == 'representation']
    assert any(row.locations[0].url == attachment and row.locations[0].role == 'landing' for row in representations)
    assert any(row.locations[0].url == pdf and row.media_type == 'application/pdf' for row in representations)


def test_wordpress_publication_date_is_only_a_discovery_hint():
    host = 'drugcaucus.senate.gov'
    payload = [{'link': URLS['drug-market-2022'], 'title': {'rendered': 'The Drug Market'}, 'date': '2022-03-04T12:00:00', 'acf': []}]
    def get(url):
        return json.dumps({'hearings': {'rest_base': 'hearings'}} if url.endswith('/types') else payload)
    listed, route = records.listed(host, get, since=date(2011, 1, 3))
    assert route == {'wordpress': True, 'wordpress_posts': {URLS['drug-market-2022']: payload[0]}}
    assert listed[0][0] == date(2022, 3, 4)
    assert records.listed(host, get, since=date(2023, 1, 3))[0] == []


def test_wordpress_full_undated_page_continues_to_later_dated_hearings():
    host = 'indian.senate.gov'
    undated = [{'link': f'https://www.{host}/u{i}', 'title': {'rendered': f'Undated {i}'},
                'date': '2022-01-01T00:00:00', 'acf': []} for i in range(100)]
    dated = [{'link': f'https://www.{host}/real-hearing', 'title': {'rendered': 'Real Hearing'},
              'date': '2022-01-02T00:00:00', 'acf': {'hearing_date_time': '2022-06-01 10:00:00'}}]
    pages = []

    def get(url):
        if url.endswith('/types'):
            return json.dumps({'hearings': {'rest_base': 'hearings'}})
        if 'page=1&' in url or url.endswith('page=1'):
            pages.append(1)
            return json.dumps(undated)
        if 'page=2&' in url or url.endswith('page=2'):
            pages.append(2)
            return json.dumps(dated)
        pages.append(url)
        return '[]'

    listed = records.wordpress_listed(host, get)
    assert pages[:2] == [1, 2]
    assert listed == [(date(2022, 6, 1), f'https://www.{host}/real-hearing', 'Real Hearing')]


def test_historical_collection_requires_explicit_sites(tmp_path):
    with pytest.raises(ValueError, match='--site'):
        records.main(tmp_path/'unused', tmp_path, tmp_path, since=date(2011, 1, 3))


@pytest.mark.parametrize('title,expected', [
    ('Business Meeting to consider S.325 and Roundtable discussion on Tribal Water Rights', 'Business Meeting'),
    ('Business Meeting to consider S.436 and Roundtable on Native American Priorities', 'Business Meeting'),
    ('Field Hearing titled, “Alaska Native Voices: A Roundtable Discussion on the Unmet Needs of Alaska Native Communities” (Part I)', 'Field Hearing'),
    ('(Rescheduled) Business Meeting to consider S. 616, S. 2868, S. 3022, H.R. 1240, S. 2796 and Legislative Hearing to receive testimony on S. 465 & S. 2695', 'Business Meeting'),
    ('(Rescheduled) Legislative Hearing to receive testimony on S. 1797, S. 1895 & H.R. 1688', 'Hearing'),
    ('[Postponed] Business Meeting to consider S. 616', 'Business Meeting'),
    ('Rescheduled: Business Meeting to consider S. 616', 'Business Meeting'),
])
def test_first_proceeding_wins_over_later_agenda_or_topic(title, expected):
    page = '<h1>' + title + '</h1><div class="jet-listing-dynamic-field__content"><strong>Date:</strong> August 4, 2026</div>'
    assert event_details(page, URLS['indian-2026-08-04'])['type'] == expected


def test_failed_page_does_not_admit_a_duplicate_of_an_already_collected_native_event(tmp_path, monkeypatch):
    import gzip
    host, url = 'indian.senate.gov', URLS['indian-housing-2026']
    native = {'eventId': '12', 'chamber': 'Senate', 'congress': 119, 'date': '2026-08-26', 'meetingStatus': 'Canceled', 'type': 'Meeting',
              'committees': [{'systemCode': 'slia00'}], 'title': 'Housing roundtable'}
    path = tmp_path/'native.jsonl.gz'; path.write_bytes(gzip.compress((json.dumps(native)+'\n').encode()))
    broken = 'https://www.indian.senate.gov/hearings/broken'
    monkeypatch.setattr(records, 'listed', lambda *a, **k: ([(date(2026,8,26), url, 'Housing'), (date(2026,8,27), broken, 'Other')], {'wordpress': True}))
    def fetch(_session, target, **kwargs):
        if target == broken: raise RuntimeError('503 Unavailable')
        return SimpleNamespace(status_code=200, content=fixture('indian-housing-2026').encode())
    monkeypatch.setattr(records_http, 'get_with_retry', fetch)
    records.main(path, tmp_path, tmp_path, as_of=date(2026,9,28), site=[host])
    saved = records_read_state(tmp_path/'senate.json.gz')
    assert saved[host]['pages'][broken]['status'] == 'error'
    assert saved[host]['workflow'][broken]['last_check']['outcome'] == 'error'
    assert saved[host]['last_attempt']['outcome'] == 'error' and '503' in saved[host]['last_attempt']['error']
    # The other page's failure no longer stops association, so no duplicate is admitted.
    assert saved[host]['workflow'][url]['events'] == ['12'] and saved[host]['workflow'][url]['candidate_events'] == []
    assert 'candidate_events' not in saved[host]['pages'][url]
    rows = list(adapt(saved, context(), meetings={(119,'senate','12'): Ref(kind='meeting',id='known')}, committee_terms={(119,'slia00'): Ref(kind='committee_term',id='term')}))
    assert not any(row.kind == 'meeting' for row in rows)


def test_offline_rematch_preserves_supported_association_despite_changed_rarity_weights(tmp_path, monkeypatch):
    import gzip
    host, url = 'drugcaucus.senate.gov', URLS['drug-market-2022']
    state = state_for('drug-market-2022', events=['12'], checked='2026-09-28', parser_version=2)
    state[host]['checked'] = '2026-09-28'
    state[host]['versions'] = {'12': ''}
    records_write_state(tmp_path/'senate.json.gz', state)
    native = {'eventId':'12', 'chamber':'Senate', 'congress':117, 'date':'2022-03-02', 'meetingStatus':'Scheduled',
              'type':'Meeting', 'title':'Hearings to examine the economics of cartels', 'committees':[{'systemCode':'scnc00'}]}
    path=tmp_path/'native.jsonl.gz'; path.write_bytes(gzip.compress((json.dumps(native)+'\n').encode()))
    monkeypatch.setattr("congress_api.matching.senate_pages.match_pages", lambda *a: ([], [], []))
    records.main(path,tmp_path,tmp_path,offline=True,as_of=date(2026,9,28),site=[host],refresh_limit=0)
    saved=records_read_state(tmp_path/'senate.json.gz')
    assert saved[host]['workflow'][url]['events'] == ['12']
    assert saved[host]['workflow'][url]['candidate_events'] == []
    assert 'events' not in saved[host]['pages'][url]
    assert '12,' in (tmp_path/'senate_hearing_pages_found.csv').read_text()
    assert '12,' in (tmp_path/'senate_witnesses_found.csv').read_text()


def test_unrelated_sites_keep_previous_refresh_population(tmp_path, monkeypatch):
    import gzip
    native={'eventId':'canceled','chamber':'Senate','congress':119,'date':'2026-08-26','meetingStatus':'Canceled',
            'type':'Hearing','title':'A canceled hearing','committees':[{'systemCode':'ssbu00'}]}
    path=tmp_path/'native.jsonl.gz';path.write_bytes(gzip.compress((json.dumps(native)+'\n').encode()))
    monkeypatch.setattr(records_http,'get_with_retry',lambda *a,**k:pytest.fail('unrelated canceled record triggered collection'))
    records.main(path,tmp_path,tmp_path,as_of=date(2026,9,28))
    assert records_read_state(tmp_path/'senate.json.gz') == {}


def test_existing_march_second_match_also_cites_the_transcript_correction():
    saved=state_for('drug-market-2022',events=['12'])
    rows=list(adapt(saved,context(),meetings={(117,'senate','12'):Ref(kind='meeting',id='existing')}))
    correction,=[row for row in rows if row.kind=='source_record' and row.url==DATE_CORRECTIONS[URLS['drug-market-2022']]['source_url']]
    links=[row for row in rows if row.kind=='material_link']
    assert links and all(any(citation.source.id==correction.id for citation in row.provenance.citations) for row in links)
    assert not any(row.kind in ('meeting','occurrence') for row in rows)


def test_root_slug_hearing_becomes_a_source_only_meeting_with_its_displayed_date():
    host = 'appropriations.senate.gov'
    url = 'https://www.appropriations.senate.gov/a-review-of-preparations-for-the-fifa-world-cup-2026'
    body = (Path(__file__).parent / 'fixtures/source_models/senate-root-slug-hearing.html').read_text()
    state = {host: {'listings': {url: ['2026-04-15', 'FIFA']}, 'pages': {url: records_parsed(body, url)}}}
    official, = official_events(state)
    rows = list(adapt(state, context(), meetings={}, committee_terms={(official['congress'], 'ssap00'): Ref(kind='committee_term', id='term')}))
    meeting, = [row for row in rows if row.kind == 'meeting']
    assert meeting.scheduled_start.date.isoformat() == '2026-04-15'
    assert meeting.title == 'A Review of Preparations for the FIFA World Cup 2026' and official['congress'] == 119


@pytest.mark.parametrize('status,recorded', [(404, 'not_found'), (403, 'error')])
def test_a_dead_page_records_its_reason_and_the_run_still_writes_its_output(status, recorded, tmp_path, monkeypatch):
    import gzip
    host, url = 'indian.senate.gov', URLS['indian-housing-2026']
    path = tmp_path/'native.jsonl.gz'; path.write_bytes(gzip.compress(b''))
    dead = 'https://www.indian.senate.gov/hearings/dead'
    monkeypatch.setattr(records, 'listed', lambda *a, **k: ([(date(2026,8,26), url, 'Housing'), (date(2026,8,27), dead, 'Other')], {'wordpress': True}))
    def fetch(_session, target, allowed=(200, 404), **kwargs):
        if target != dead:
            return SimpleNamespace(status_code=200, content=fixture('indian-housing-2026').encode())
        if status not in allowed:
            raise RuntimeError(f'{status} Forbidden')
        return SimpleNamespace(status_code=status, content=b'')
    monkeypatch.setattr(records_http, 'get_with_retry', fetch)
    records.main(path, tmp_path, tmp_path, as_of=date(2026,9,28), site=[host])
    saved = records_read_state(tmp_path/'senate.json.gz')[host]
    assert saved['workflow'][dead]['last_check']['outcome'] == recorded
    assert saved['pages'][url].get('event')
    assert list(tmp_path.glob('*.csv'))


def test_a_failed_listing_still_fails_the_run(tmp_path, monkeypatch):
    import gzip
    host = 'indian.senate.gov'
    path = tmp_path/'native.jsonl.gz'; path.write_bytes(gzip.compress(b''))
    def refused(*args, **kwargs):
        raise RuntimeError('503 Unavailable')
    monkeypatch.setattr(records, 'listed', refused)
    with pytest.raises(RuntimeError, match='503'):
        records.main(path, tmp_path, tmp_path, as_of=date(2026,9,28), site=[host])


def outage_run(tmp_path, monkeypatch, urls, *, answering=(), statusless=(), **kwargs):
    import gzip
    from congress_api.transport.http import HttpRequestError
    host = 'indian.senate.gov'
    path = tmp_path/'native.jsonl.gz'; path.write_bytes(gzip.compress(b''))
    monkeypatch.setattr(records, 'listed', lambda *a, **k: ([(date(2026,8,26), url, 'Hearing') for url in urls], {'wordpress': True}))
    fetched = []
    def fetch(_session, target, **_):
        fetched.append(target)
        if target in answering:
            return SimpleNamespace(status_code=404, content=b'')
        if target in statusless:
            raise OSError('connection refused')
        raise HttpRequestError('403 Forbidden', 403)
    monkeypatch.setattr(records_http, 'get_with_retry', fetch)
    records.main(path, tmp_path, tmp_path, as_of=date(2026,9,28), site=[host], **kwargs)
    return fetched


def hearing_urls(count):
    return [f'https://www.indian.senate.gov/hearings/h{index:02}' for index in range(count)]


def test_three_fresh_failures_with_no_answer_fail_the_run(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match='site-wide page outage'):
        outage_run(tmp_path, monkeypatch, hearing_urls(3))
    saved = records_read_state(tmp_path/'senate.json.gz')['indian.senate.gov']
    assert saved['last_attempt']['outcome'] == 'error' and len(saved['pages']) == 3


def test_two_failures_stay_page_outcomes(tmp_path, monkeypatch):
    outage_run(tmp_path, monkeypatch, hearing_urls(2))
    assert list(tmp_path.glob('*.csv'))


def test_one_answer_keeps_failures_as_page_outcomes(tmp_path, monkeypatch):
    urls = hearing_urls(6)
    outage_run(tmp_path, monkeypatch, urls, answering={urls[-1]})
    assert list(tmp_path.glob('*.csv'))


def test_a_host_stops_after_ten_failures_in_a_row(tmp_path, monkeypatch):
    fetched = []
    with pytest.raises(RuntimeError, match='site-wide page outage'):
        fetched = outage_run(tmp_path, monkeypatch, hearing_urls(12))
    saved = records_read_state(tmp_path/'senate.json.gz')['indian.senate.gov']
    assert sum(page.get('status') == 'error' for page in saved['pages'].values()) == 10


def test_failed_pages_count_against_the_refresh_limit(tmp_path, monkeypatch):
    urls = hearing_urls(8)
    with pytest.raises(RuntimeError):
        outage_run(tmp_path, monkeypatch, urls, limit=4)
    saved = records_read_state(tmp_path/'senate.json.gz')['indian.senate.gov']
    assert sum(page.get('status') == 'error' for page in saved['pages'].values()) == 4


def saved_error_pages(tmp_path, urls, *, host_answered):
    check = {'mode': 'live', 'outcome': 'error', 'error': '403 Forbidden', **({'host_answered': True} if host_answered else {})}
    state = {'indian.senate.gov': {'listings': {url: ['2026-08-26', 'Hearing'] for url in urls}, 'checked': '2026-09-28', 'wordpress': True,
                                   'pages': {url: {'title': '', 'lines': [], 'witnesses': [], 'documents': [], 'status': 'error'} for url in urls},
                                   'workflow': {url: {'last_check': dict(check)} for url in urls}}}
    records_write_state(tmp_path/'senate.json.gz', state)


def test_legacy_error_pages_with_a_status_are_known_and_without_one_are_not(tmp_path, monkeypatch):
    # State saved before the marker existed (green-e2): its receipts decide. Defect: treating
    # every marker-less error page as unknown fails a Budget-like host on every run.
    urls = hearing_urls(7)
    saved_error_pages(tmp_path, urls, host_answered=False)
    state = records_read_state(tmp_path/'senate.json.gz')
    for url in urls:
        state['indian.senate.gov']['workflow'][url]['last_check']['receipts'] = [dict(url=url, status_code=403)]
    records_write_state(tmp_path/'senate.json.gz', state)
    outage_run(tmp_path, monkeypatch, urls)
    saved = records_read_state(tmp_path/'senate.json.gz')['indian.senate.gov']
    assert all(saved['workflow'][url]['last_check'].get('host_answered') for url in urls)


def test_a_repeat_run_over_never_fetched_pages_fails(tmp_path, monkeypatch):
    # Pages in error that never answered while their host did are not known page failures.
    urls = hearing_urls(4)
    saved_error_pages(tmp_path, urls, host_answered=False)
    with pytest.raises(RuntimeError, match='site-wide page outage'):
        outage_run(tmp_path, monkeypatch, urls)


def test_one_answer_then_ten_failures_fails_the_host(tmp_path, monkeypatch):
    urls = hearing_urls(12)
    with pytest.raises(RuntimeError, match='site-wide page outage'):
        outage_run(tmp_path, monkeypatch, urls, answering={urls[0]})
    saved = records_read_state(tmp_path/'senate.json.gz')['indian.senate.gov']
    assert sum(page.get('status') == 'error' for page in saved['pages'].values()) == 10
    # The outage tail is not confirmed as page failures.
    assert not any(record.get('last_check', {}).get('host_answered') for record in saved['workflow'].values())


def test_known_page_failures_do_not_trip_an_outage(tmp_path, monkeypatch):
    # Budget's case: pages that failed while the host answered stay page outcomes.
    urls = hearing_urls(7)
    saved_error_pages(tmp_path, urls, host_answered=True)
    fetched = outage_run(tmp_path, monkeypatch, urls)
    assert set(urls) <= set(fetched)
    assert list(tmp_path.glob('*.csv'))
    saved = records_read_state(tmp_path/'senate.json.gz')['indian.senate.gov']
    assert all(saved['workflow'][url]['last_check']['host_answered'] for url in urls)


def test_failures_after_the_last_answer_are_not_confirmed_and_fail_the_run(tmp_path, monkeypatch):
    # Red-e2: one page answers, then the site goes down. Defect: marking every failure known
    # because some page answered, so the next run exits 0 over the outage.
    urls = hearing_urls(6)
    with pytest.raises(RuntimeError, match='site-wide page outage'):
        outage_run(tmp_path, monkeypatch, urls, answering={urls[0]})
    saved = records_read_state(tmp_path/'senate.json.gz')['indian.senate.gov']
    assert not any(record.get('last_check', {}).get('host_answered') for record in saved['workflow'].values())
    with pytest.raises(RuntimeError, match='site-wide page outage'):
        outage_run(tmp_path, monkeypatch, urls, answering={urls[0]})


def test_failures_with_no_http_status_are_not_known_page_failures(tmp_path, monkeypatch):
    # Pages that got no HTTP status at all, even before a later answer, are not page outcomes.
    urls = hearing_urls(6)
    with pytest.raises(RuntimeError, match='no\nHTTP status|no HTTP status'):
        outage_run(tmp_path, monkeypatch, urls, answering={urls[-1]}, statusless=set(urls[:3]))
    saved = records_read_state(tmp_path/'senate.json.gz')['indian.senate.gov']
    assert not any(saved['workflow'][url]['last_check'].get('host_answered') for url in urls[:3])


def test_the_host_answered_marker_survives_a_round_trip(tmp_path, monkeypatch):
    urls = hearing_urls(6)
    outage_run(tmp_path, monkeypatch, urls, answering={urls[-1]})
    saved = records_read_state(tmp_path/'senate.json.gz')['indian.senate.gov']
    assert [url for url in urls if saved['workflow'][url]['last_check'].get('host_answered')] == urls[:-1]
    records_write_state(tmp_path/'again.json.gz', records_normalize(records_read_state(tmp_path/'senate.json.gz')))
    again = records_read_state(tmp_path/'again.json.gz')['indian.senate.gov']
    assert all(again['workflow'][url]['last_check']['host_answered'] for url in urls[:-1])

