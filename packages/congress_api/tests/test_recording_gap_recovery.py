"""Source-proven open portions must survive discovery and media adaptation."""
from datetime import UTC, datetime

import pytest
from committee_meeting.common import Ref
from congress_api.adapters.common import AdapterContext
from congress_api.adapters.senate import records as adapt
from congress_api.matching.senate_pages import match_pages
from test_explorer_senate_adapter import retained_page

PAGE = 'https://www.armed-services.senate.gov/hearings/strategic-forces'
PLAYER = 'https://www.senate.gov/isvp/?auto_play=false&comm=armed&filename=armedA032625'


@pytest.mark.parametrize('title,native_type,expected', [
    ('Open hearings to examine strategic forces; to be immediately followed by a closed session.', 'Meeting', True),
    ('Open and closed hearings to examine strategic forces.', 'Meeting', True),
    ('Hearings to examine strategic forces; with the possibility of a closed session following the open session.', 'Meeting', True),
    ('Closed hearings to examine strategic forces.', 'Meeting', False),
    ('Briefing on strategic forces.', 'Meeting', True),
    ('Executive session to examine strategic forces.', 'Meeting', True),
    ('Business meeting to consider strategic forces.', 'Open Business Meeting', True),
])
def test_page_discovery_does_not_assume_closed_from_proceeding_kind(title, native_type, expected):
    meeting = dict(eventId='336743', date='2025-03-26', chamber='Senate', type=native_type, title=title,
                   committees=[{'systemCode': 'ssas16'}])
    state = {'armed-services.senate.gov': {'listings': {PAGE: ['2025-03-26', title]}, 'pages': {
        PAGE: {'title': title, 'lines': ['March 26, 2025', title], 'documents': [], 'witnesses': []}}}}
    found, _, _ = match_pages([meeting], state)
    assert bool(found) is expected
    if expected:
        assert found[0]['event_id'] == '336743' and found[0]['page'] == PAGE


def test_embedded_recording_is_linked_only_to_an_established_page_match():
    ctx = AdapterContext(now=datetime(2026, 9, 28, tzinfo=UTC), input_id='test', provider='senate.committee',
                         ids=lambda kind, key: kind + ':' + key)
    metadata = {'media': [
        {'tag': 'iframe', 'attributes': {'src': PLAYER, 'title': 'Strategic forces'}},
        {'tag': 'iframe', 'attributes': {'src': 'https://maps.example.org/widget'}},
        {'tag': 'iframe', 'attributes': {'src': 'https://example.org/?comm=armed&filename=armedA032625'}},
    ]}
    page = {'title': 'Strategic forces', 'lines': [], 'documents': [], 'witnesses': [], 'events': ['336743'], 'page_metadata': metadata}
    state = {'armed-services.senate.gov': {'pages': {PAGE: page}}}
    rows = list(adapt(state, ctx, meetings={(119, 'senate', '336743'): Ref(kind='meeting', id='known')}))
    material, = [r for r in rows if r.kind == 'material']
    assert material.details.type == 'recording' and material.details.provider == 'senate'
    assert material.identifiers[0].value == 'armedA032625'
    link, = [r for r in rows if r.kind == 'material_link']
    assert link.subject.id == 'known' and link.role == 'recording'
    assert {c.selector for c in link.provenance.citations} == {'/events/0', '/page_metadata/media/0'}
    source = retained_page(rows, page)
    assert source.payload['page_metadata'] == metadata
    sources = {r.id: r for r in rows if r.kind == 'source_record'}
    citations = {c.selector: c for c in link.provenance.citations}
    assert citations['/page_metadata/media/0'].source.id == source.id
    assert sources[citations['/events/0'].source.id].payload == {'events': ['336743']}
    unlinked = list(adapt(state, ctx, meetings={}))
    assert len([r for r in unlinked if r.kind == 'material']) == 1
    assert not [r for r in unlinked if r.kind == 'material_link']


def test_real_strategic_forces_open_portion_reaches_recording_output():
    import json
    from pathlib import Path

    from congress_api.parsers.senate import parse_page
    fixture = Path(__file__).parent / 'fixtures/meeting_inventory/armed-open-closed.html'
    info = json.loads(fixture.with_suffix('.json').read_text())
    page = parse_page(fixture.read_bytes(), info['url']).source_dict()
    state = {'armed-services.senate.gov': {'listings': {info['url']: ['2025-03-26', page['title']]}, 'pages': {info['url']: page}}}
    found, _, _ = match_pages([info['native']], state)
    assert [r['event_id'] for r in found] == ['336743']
    page['events'] = ['336743']
    ctx = AdapterContext(now=datetime(2026, 9, 28, tzinfo=UTC), input_id='real-source', provider='senate.committee', ids=lambda k, v: k + ':' + v)
    rows = list(adapt(state, ctx, meetings={(119, 'senate', '336743'): Ref(kind='meeting', id='known')}))
    video, = [r for r in rows if r.kind == 'material' and r.details.type == 'recording']
    assert video.identifiers[0].value == 'armedA032625'
    assert any(r.kind == 'material_link' and r.role == 'recording' and r.material.id == video.id for r in rows)


def test_real_publisher_no_broadcast_notice_is_scoped_not_a_failed_search():
    import json
    from pathlib import Path

    from congress_api.parsers.senate import parse_page
    fixture = Path(__file__).parent / 'fixtures/meeting_inventory/agriculture-no-broadcast.html'
    info = json.loads(fixture.with_suffix('.json').read_text())
    page = parse_page(fixture.read_bytes(), info['url']).source_dict()
    assert page['page_metadata']['video_messages'] == [{'text': 'There is no video broadcast for this event.', 'attributes': {'class': 'Hearing__videoMessageContent'}}]
    page['events'] = ['338551']
    ctx = AdapterContext(now=datetime(2026, 9, 29, 12, tzinfo=UTC), input_id='real-source', provider='senate.committee', ids=lambda k, v: k + ':' + v)
    rows = list(adapt({'agriculture.senate.gov': {'pages': {info['url']: page}}}, ctx,
                      meetings={(119, 'senate', '338551'): Ref(kind='meeting', id='known')}))
    finding, = [r for r in rows if r.kind == 'assessment' and r.aspect == 'recording']
    assert finding.status == 'not_applicable'
    assert finding.explanation == 'There is no video broadcast for this event.'
    assert finding.scope.startswith('Video broadcast by the committee')
    assert not [r for r in rows if r.kind == 'material' and r.details.type == 'recording']


@pytest.mark.parametrize('access,day,expected', [
    ('unknown', '2025-03-26', 'partly_closed'),
    ('unknown', '2025-03-27', None),
    ('closed', '2025-03-26', 'closed'),
    ('partly_closed', '2025-03-26', None),
])
@pytest.mark.parametrize('has_prior_alternative', [False, True])
def test_real_access_heading_updates_only_matching_existing_sitting(access, day, expected, has_prior_alternative):
    import json
    from pathlib import Path

    from committee_explorer.assemble import Assembly
    from committee_meeting.meetings import Meeting, MeetingOccurrence
    from committee_meeting.provenance import AlternativeValue, FieldEvidence
    from congress_api.adapters.common import reported_time
    from congress_api.models.senate import SenatePage
    from congress_api.parsers.senate import parse_page
    fixture = Path(__file__).parent / 'fixtures/meeting_inventory/armed-open-closed.html'
    info = json.loads(fixture.with_suffix('.json').read_text())
    page = parse_page(fixture.read_bytes(), info['url']).source_dict()
    page['events'] = ['336743']
    typed_page = SenatePage.model_validate(page)
    assert typed_page.page_metadata.heading_prefixes[0].text == 'Open/Closed:'
    ctx = AdapterContext(now=datetime(2026, 9, 28, tzinfo=UTC), input_id='real-source', provider='senate.committee', ids=lambda k, v: k + ':' + v)
    meeting = Ref(kind='meeting', id='known')
    native_source = ctx.source('native-event', {'eventId': 336743})
    original = MeetingOccurrence(id='existing-occurrence', meeting=meeting, access=access,
                                 scheduled_start=reported_time(day), provenance=ctx.evidence(native_source),
                                 field_evidence=(FieldEvidence(path='/access', selected=ctx.evidence(native_source),
                                     alternatives=(AlternativeValue(value='open', provenance=ctx.evidence(native_source)),),
                                     selection_reason='An earlier source supplied an unselected alternative.'),) if has_prior_alternative else ())
    rows = list(adapt({'armed-services.senate.gov': {'pages': {info['url']: typed_page}}}, ctx,
                      meetings={(119, 'senate', '336743'): meeting}, occurrence_records={original.id: original}))
    updated = [r for r in rows if r.kind == 'occurrence']
    if expected is None:
        assert not updated
    else:
        result, = updated
        assert result.id == original.id and result.access == expected
        assert result.provenance == original.provenance
        field, = result.field_evidence
        if has_prior_alternative:
            assert field.alternatives[0] == original.field_evidence[0].alternatives[0]
        if access == 'unknown':
            assert all(a.value != 'unknown' for a in field.alternatives)
            assert '/page_metadata/heading_prefixes/0' in {c.selector for c in field.selected.citations}
        else:
            assert field.selected == original.provenance
            assert field.alternatives[-1].value == 'partly_closed'
        assembly = Assembly(ids=ctx.ids, now=ctx.now)
        assembly.add([native_source, Meeting(id=meeting.id, provenance=original.provenance), original])
        assembly.add(rows)
        merged = assembly.records[('occurrence', original.id)]
        assert merged.access == expected and merged.field_evidence == result.field_evidence
        assert sum(record.kind == 'occurrence' for record in assembly.records.values()) == 1
        assembly.finish()
        conflicts = [record for record in assembly.records.values() if record.kind == 'data_issue'
                     and record.category == 'conflicting' and record.field_path == '/access']
        assert bool(conflicts) == (has_prior_alternative or access == 'closed')
