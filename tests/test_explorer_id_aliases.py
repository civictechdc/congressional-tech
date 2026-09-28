"""A later native identifier must not rename a published official-site meeting."""
import gzip
import json

from committee_explorer.export import _retain_senate_meeting_ids
from committee_explorer.ids import IdRegistry
from congress_api.adapters.meetings import meeting_key
from test_explorer_export import native, run, write_meetings


URL = 'https://www.indian.senate.gov/hearings/tribal-infrastructure-roundtable/'


def source_state(events=(), urls=(URL,)):
    return {'indian.senate.gov': {'pages': {url: {
        'title': 'Roundtable on tribal infrastructure',
        'event': {'title': 'Roundtable on tribal infrastructure', 'date': '2026-08-26',
                  'type': 'Roundtable', 'url': url},
        'events': list(events), 'documents': [], 'witnesses': [{'name': 'Alex Smith', 'position': 'Director'}],
    } for url in urls}}}


def native_row():
    return {**native(), 'chamber': 'Senate', 'congress': 119, 'eventId': '99901',
            'date': '2026-08-26', 'title': 'Roundtable on tribal infrastructure', 'type': 'Hearing',
            'committees': [{'systemCode': 'slia00', 'name': 'Indian Affairs'}],
            'witnesses': [], 'meetingDocuments': [], 'relatedItems': {}}


def test_alias_requires_existing_target_and_cannot_rebind_published_ids(tmp_path):
    ids = IdRegistry(tmp_path / 'ids.json')
    assert not ids.alias('meeting', 'new', 'unknown')
    assert ids.existing('meeting', 'new') is None
    old = ids('meeting', 'old')
    assert ids.alias('meeting', 'new', 'old')
    assert ids('meeting', 'new') == old
    other = ids('meeting', 'other')
    assert not ids.alias('meeting', 'other', 'old')
    assert ids('meeting', 'other') == other != old
    ids.save()
    assert IdRegistry(ids.path).existing('meeting', 'new') == old


def test_native_arrival_preserves_meeting_and_appearance_ids(tmp_path):
    state = tmp_path / 'senate.json.gz'
    state.write_bytes(gzip.compress(json.dumps(source_state()).encode()))
    path = write_meetings(tmp_path, [])
    _, first = run(tmp_path, path, senate_state=state)
    first_meeting, = [r for r in first.records if r.kind == 'meeting']
    first_appearance, = [r for r in first.records if r.kind == 'appearance']
    row = native_row()
    write_meetings(tmp_path, [row])
    state.write_bytes(gzip.compress(json.dumps(source_state(events=[row['eventId']])).encode()))
    _, second = run(tmp_path, path, senate_state=state)
    meeting, = [r for r in second.records if r.kind == 'meeting']
    appearance, = [r for r in second.records if r.kind == 'appearance']
    assert meeting.id == first_meeting.id
    assert appearance.id == first_appearance.id
    assert appearance.meeting.id == meeting.id
    assert any(i.scheme == 'senate.committee:page' and i.value == URL for i in meeting.identifiers)
    assert any(i.scheme == 'congress.gov:event' and i.value == row['eventId'] for i in meeting.identifiers)
    _, third = run(tmp_path, path, senate_state=state)
    assert {r.id for r in third.records if r.kind == 'meeting'} == {meeting.id}


def test_two_published_source_ids_do_not_merge_into_one_new_native_id(tmp_path):
    ids = IdRegistry(tmp_path / 'ids.json')
    urls = (URL, URL + 'second')
    previous = {ids('meeting', 'senate.committee|' + url) for url in urls}
    row = native_row()
    assert _retain_senate_meeting_ids([row], source_state(events=[row['eventId']], urls=urls), ids) == 0
    assert ids('meeting', meeting_key(row)) not in previous


def test_ambiguous_event_and_different_congress_do_not_alias(tmp_path):
    ids = IdRegistry(tmp_path / 'ids.json')
    old = ids('meeting', 'senate.committee|' + URL)
    row = native_row()
    assert _retain_senate_meeting_ids([row], source_state(events=[row['eventId'], '99902']), ids) == 0
    assert _retain_senate_meeting_ids([row, {**row, 'congress': 118}], source_state(events=[row['eventId']]), ids) == 0
    assert _retain_senate_meeting_ids([{**row, 'congress': 118}], source_state(events=[row['eventId']]), ids) == 0
    assert ids.existing('meeting', meeting_key(row)) is None
    assert ids.existing('meeting', 'senate.committee|' + URL) == old
