"""Source interpretation stays usable without normalized output adapters."""
from copy import deepcopy
from datetime import UTC, date, datetime

from congress_api.matching.senate_events import official_events, dated_access, no_broadcast_notices, reconciled_event_type
from congress_api.parsers.observations import caption_observations, live_receipt, source_check

NOW = datetime(2026, 10, 4, tzinfo=UTC)
URL = 'https://www.indian.senate.gov/hearings/example/'


def test_official_admission_is_source_only_and_preserves_input():
    event = {'title': 'Official roundtable', 'type': 'Roundtable', 'date': '2026-01-02', 'url': URL}
    state = {'indian.senate.gov': {'pages': {URL: {'event': event, 'events': ['12']}}}}
    before = deepcopy(state)
    official, = official_events(state)
    assert (official['congress'], official['committee_code']) == (119, 'slia00')
    assert state == before
    assert reconciled_event_type(event, 'hearing') == 'roundtable'
    assert reconciled_event_type({'title': 'Roundtable'}, 'hearing') == 'hearing'
    state['indian.senate.gov']['pages'][URL]['event']['url'] = 'https://other.senate.gov/example/'
    assert list(official_events(state)) == []


def test_dated_access_and_exact_no_broadcast_preserve_selectors():
    page = {'lines': ['Date: October 1, 2026'], 'page_metadata': {
        'heading_prefixes': [{'text': 'OPEN:'}], 'video_messages': [
            {'text': 'There is no video broadcast for this event.'}, {'text': 'No video yet'}]}}
    access = dated_access(URL, page)
    assert (access.access, access.day, access.label_selector, access.date_selector) == (
        'open', date(2026, 10, 1), '/page_metadata/heading_prefixes/0', '/lines/0')
    assert list(no_broadcast_notices(page)) == [(0, 'There is no video broadcast for this event.')]
    page['page_metadata']['heading_prefixes'].append({'text': 'Closed'})
    assert dated_access(URL, page) is None


def test_negative_caption_requires_actual_time_and_scope_and_keeps_prior_success():
    receipt = {'outcome': 'error', 'observed_at': '2026-10-03T00:00:00Z', 'scope': 'English',
               'last_successful': {'outcome': 'available', 'observed_at': '2026-10-01T00:00:00Z', 'scope': {'language': 'en'}}}
    before = deepcopy(receipt)
    latest, earlier = caption_observations('youtube', 'none', receipt, NOW)
    assert latest.status == 'error'
    assert earlier.status == 'available' and earlier.observed_at < latest.observed_at
    assert earlier.selector == '/receipt/last_successful' and earlier.suffix == '|last-successful'
    assert receipt == before
    for observed, scope in [('2026-10-01', 'English'), ('2027-01-01T00:00:00Z', 'English'), ('2026-10-01T00:00:00Z', '')]:
        observation, = caption_observations('youtube', 'none', {'outcome': 'not_found', 'observed_at': observed, 'scope': scope}, NOW)
        assert observation.status == 'unknown'
    indexed, = caption_observations('youtube', 'manual', None, NOW)
    assert indexed.status == 'available' and indexed.observed_at is None


def test_live_checks_keep_latest_failure_separate_from_success():
    receipt = {'url': URL, 'status_code': 200, 'outcome': 'retrieved', 'completed_at': '2026-10-01T00:00:00Z'}
    record = {'observation_check': {'mode': 'live', 'receipts': [receipt]},
              'last_check': {'mode': 'live', 'outcome': 'error', 'completed_at': '2026-10-03T00:00:00Z'}}
    assert live_receipt(record, URL, NOW) == (datetime(2026, 10, 1, tzinfo=UTC), 'retrieved')
    assert live_receipt(record, URL + 'other', NOW) is None
    witness = {'observation_check': {'mode': 'live', 'url': URL, 'status_code': 200, 'outcome': 'present', 'completed_at': receipt['completed_at']}, 'last_check': record['last_check']}
    check = source_check(witness, URL, NOW)
    assert check.successful and check.status_code == 200 and check.latest_failed


def test_last_successful_caption_check_survives_repeated_failures_without_nesting():
    from congress_api.parsers.observations import last_successful_caption_check
    positive = {'outcome': 'available', 'scope': 'English', 'observed_at': '2026-10-01T00:00:00Z'}
    previous = {'outcome': 'error', 'last_successful': {**positive, 'last_successful': {'outcome': 'available'}}}
    assert last_successful_caption_check(previous) == positive
    assert last_successful_caption_check({'outcome': 'unknown'}) is None


def test_archive_probe_negatives_require_live_day_and_complete_url_scope():
    from congress_api.parsers.senate_probes import probe_observation
    from congress_api.parsers.senate_player import player_url
    url = player_url('ag', 'ag100126')
    observation = {'source': 'HEAD', 'checked': '2026-10-01', 'urls': [url]}
    result = probe_observation('ag|2026-10-01', observation, NOW)
    assert result.observed_day == date(2026, 10, 1) and result.valid_urls
    assert dict(result.positive_players)['ag100126'] == url
    assert {filename for filename, scope in result.tested_players} == {'ag100126', 'agA100126', 'agB100126', 'ag100126p'}
    imported = probe_observation('ag|2026-10-01', {**observation, 'source': 'research HEAD cache'}, NOW)
    assert imported.observed_day is None and not imported.tested_players
    incomplete = probe_observation('ag|2026-10-01', {**observation, 'urls': [url, 'bad']}, NOW)
    assert incomplete.positive_players and not incomplete.tested_players


def test_source_only_admission_refuses_retained_associations_and_candidates():
    from congress_api.matching.senate_events import source_only_event_allowed
    assert source_only_event_allowed({})
    assert not source_only_event_allowed({'events': ['12']})
    assert not source_only_event_allowed({'candidate_events': ['12']})


def test_foreign_player_url_cannot_establish_senate_probe_availability():
    from committee_meeting.common import Ref
    from congress_api.adapters import inventory
    from congress_api.adapters.common import AdapterContext
    from congress_api.parsers.senate_probes import probe_observation

    observation = {'source': 'HEAD', 'checked': '2026-10-01',
                   'urls': ['https://other.gov/isvp/?comm=ag&filename=ag100126']}
    parsed = probe_observation('ag|2026-10-01', observation, NOW)
    assert not parsed.valid_urls
    assert not parsed.positive_players and not parsed.tested_players
    context = AdapterContext(now=NOW, provider='test', input_id='test',
                             ids=lambda kind, key: kind + ':' + key)
    materials = {('senate', name): Ref(kind='material', id=name)
                 for name in ('ag100126', 'agA100126')}
    records = list(inventory.records({'probes': {'ag|2026-10-01': observation}},
                                    context, meetings={}, materials=materials))
    assert not any(record.kind == 'assessment' for record in records)
    assert any(record.kind == 'data_issue' and 'URL list' in record.summary for record in records)
