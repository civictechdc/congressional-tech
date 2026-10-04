"""Provider identity and publisher types agree without flattening output taxonomies."""
from datetime import datetime, timezone
from hashlib import sha256
import pytest

from congress_api.adapters import house, meetings, recordings
from congress_api.adapters.common import AdapterContext
from congress_api.parsers.house_documents import document_kind
from congress_api.retention.document_index import fill_document_kind


def context():
    return AdapterContext(now=datetime(2026, 10, 4, tzinfo=timezone.utc), input_id='native', provider='test',
                          ids=lambda kind, key: kind + '-' + sha256(key.encode()).hexdigest()[:24])


@pytest.mark.parametrize('url', [
    'https://www.youtube-nocookie.com/embed/abcdefghijk?start=12',
    'https://www.youtube.com/watch?v=abcdefghijk&feature=shared#t=12',
    'https://youtu.be/abcdefghijk',
    'https://www.youtube.com/live/abcdefghijk',
    'https://www.youtube.com/shorts/abcdefghijk',
    'https://www.youtube.com/v/abcdefghijk',
    'http://www.senate.gov/isvp/?comm=epw&filename=epw120623&part=one%2Ftwo',
])
def test_native_and_curated_recordings_share_provider_identity(url):
    ctx = context()
    row = dict(congress=118, chamber='house', eventId='123456', videos=[dict(url=url)])
    native = list(meetings.records([row], ctx))
    curated = list(recordings.records([dict(event_id='123456', recording=url)], ctx, meetings={}))
    a = next(r for r in native if r.kind == 'material')
    b = next(r for r in curated if r.kind == 'material')
    assert (a.id, a.identifiers, a.details.provider) == (b.id, b.identifiers, b.details.provider)
    assert next(r for r in native if r.kind == 'representation').locations[0].url == url
    assert next(r for r in native if r.kind == 'source_record').payload['videos'][0]['url'] == url


def test_house_table_of_contents_keeps_coarse_and_detailed_kinds():
    assert document_kind('TC', '', 'https://docs.house.gov/123.pdf') == 'hearing record'
    assert house.DOCUMENT_CATEGORIES['TC'] == 'hearing_record'
    assert meetings.category({'documentType': 'Hearing: Table of Contents', 'name': 'Witness testimony'}) == 'hearing_record'
    row = {'source_document_type': ['TC']}
    fill_document_kind(row)
    assert row['document_kind'] == ['table-of-contents']
    assert row['source_document_type'] == ['TC']


@pytest.mark.parametrize('token', [
    'https://example.gov/embed/abcdefghijk?next=https://youtube.com/watch?v=abcdefghijk',
    'https://youtube.com.evil.test/watch?v=abcdefghijk',
    'https://other.gov/isvp/?comm=epw&filename=epw120623',
    'https://www.youtube.com/watch?v=abcdefghijkl',
])
def test_provider_requires_native_host_and_complete_identity(token):
    from congress_api.parsers.media import recording_reference
    parsed = recording_reference(token)
    assert parsed.provider is None
    assert parsed.key == 'offsite|' + token
    assert parsed.url == token


def test_core_parser_accepts_bare_ids_and_refuses_unusable_values():
    from congress_api.parsers.media import recording_reference
    assert recording_reference('abcdefghijk').key == 'youtube|abcdefghijk'
    for token in (None, 1, '', 'relative/player', 'https://[broken'):
        assert recording_reference(token) is None


def test_literal_meanings_do_not_infer_from_document_titles():
    from congress_api.parsers.document_types import document_type
    assert document_type('  Hearing: Table   of Contents ') == document_type('TC') == 'table-of-contents'
    assert document_type('Statement by a witness') is None
    assert document_type(None) is None


def test_unknown_native_recordings_keep_event_scoped_ids_and_exact_urls():
    ctx = context()
    url = 'http://example.gov/a/../player?literal=one%2Ftwo#part-1'
    row = dict(congress=118, chamber='house', eventId='123456', videos=[dict(url=url)])
    result = list(meetings.records([row], ctx))
    material = next(r for r in result if r.kind == 'material')
    assert material.id == ctx.ids('material', 'congress.gov|118|house|123456|videos|' + url)
    assert material.details.provider is None
    assert not material.identifiers
    assert next(r for r in result if r.kind == 'representation').locations[0].url == url


@pytest.mark.parametrize(('code', 'expected'), [
    ('TC', 'hearing_record'), ('BR', 'bill_text'), ('WB', 'biography'), ('HT', 'transcript'),
    ('SD', 'transcript'),
])
def test_house_native_codes_preserve_priority_and_raw_facts(code, expected):
    ctx = context()
    url = 'https://docs.house.gov/unchanged.pdf'
    group = dict(type=code, description='Transcript', files=[dict(url=url)])
    saved = {'evidence': {'document_groups': [group]}}
    result = list(house.records({'123456': saved}, ctx, meetings={}))
    material = next(r for r in result if r.kind == 'material')
    assert material.details.category == expected
    assert material.id == ctx.ids('material', 'docs.house.gov|None|123456|document|' + url)
    assert next(r for r in result if r.kind == 'source_record').payload == saved


@pytest.mark.parametrize(('row', 'expected'), [
    ({'documentType': 'Support Document', 'name': 'Transcript'}, 'transcript'),
    ({'kind': 'witness biography', 'name': ''}, 'biography'),
    ({'kind': 'transcript', 'name': ''}, 'transcript'),
    ({'kind': 'biography', 'name': 'Witness statement'}, 'statement'),
    ({'documentType': 'legislative text', 'name': 'Biography'}, 'bill_text'),
])
def test_coarse_category_keeps_existing_fallback_order(row, expected):
    assert meetings.category(row) == expected


def meeting_with_players():
    return dict(congress=119, chamber='House', eventId='123456', type='Hearing', title='Test hearing',
                meetingStatus='Scheduled', date='2026-09-01T10:00:00Z', committees=[dict(systemCode='hsju00', name='Judiciary')],
                videos=[dict(url=url) for url in (
                    'https://www.youtube-nocookie.com/embed/abcdefghijk',
                    'https://other.gov/player?next=https://youtube.com/watch?v=lmnopqrstuv',
                    'https://other.gov/isvp/?comm=epw&filename=foreign',
                    'http://www.senate.gov/isvp/?comm=epw&filename=epw120623#part',
                )])


def test_core_recording_index_uses_provider_url_identity():
    from congress_api.matching.recordings import build, _place_assigned
    row = meeting_with_players()
    result, = build([row], [], [], [], [], [], {}, {}, {})
    assert result['youtube_ids'] == 'abcdefghijk'
    assert result['senate_urls'] == row['videos'][3]['url']
    youtube, senate, other = [], [], []
    for token in (row['videos'][0]['url'], row['videos'][1]['url'], row['videos'][2]['url'],
                  row['videos'][3]['url'], 'manual-id'):
        _place_assigned(token, youtube, senate, other)
    assert youtube == ['abcdefghijk', 'manual-id']
    assert senate == [row['videos'][3]['url']]
    assert other == [row['videos'][1]['url'], row['videos'][2]['url']]


def test_core_gpo_meeting_loader_uses_provider_url_identity(tmp_path):
    from congress_api.cli.gpo_match import load_meetings
    from congress_api.retention.meetings import write
    row = meeting_with_players()
    path = tmp_path / 'meetings.jsonl.gz'
    write({'https://api.congress.gov/event/123456': row}, path)
    result, = load_meetings(path)['hsju00']['2026-09-01']
    assert result['videos'] == ['abcdefghijk']
    assert result['offsite'] == [row['videos'][3]['url']]


def test_core_transcript_recording_context_uses_provider_url_identity():
    from congress_api.transcripts.context import recording_sources
    row = meeting_with_players()
    assert recording_sources(row) == (['abcdefghijk'], [row['videos'][3]['url']])
