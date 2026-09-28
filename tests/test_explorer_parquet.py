"""Verify browser tables against source-backed records, including missing links."""
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from committee_explorer.browser import package, verify
from committee_explorer.export import export
from test_explorer_export import native, write_meetings, NOW


def test_parquet_export_preserves_browse_population_files_and_raw_evidence(tmp_path):
    row = native()
    row['meetingDocuments'].append({'name': 'Printed hearing', 'documentType': 'Transcript', 'format': 'PDF',
                                   'url': 'https://example.org/hearing.pdf'})
    source = write_meetings(tmp_path, [row, {**row, 'eventId': '106246', 'meetingStatus': 'Canceled'}])
    manifest, catalog = export(meetings=source, output_dir=tmp_path/'out', state_dir=tmp_path/'state', as_of=NOW, format='parquet')
    _, root, _ = verify(tmp_path/'out')
    assert len(list(root.glob('*.parquet'))) == 6
    assert not (root/'catalog.json').exists()
    meetings = pq.read_table(root/'meetings.parquet').to_pylist()
    materials = pq.read_table(root/'materials.parquet').to_pylist()
    sources = pq.read_table(root/'sources.parquet').to_pylist()
    assert {r['id'] for r in meetings} == {r.id for r in catalog.records if r.kind == 'meeting'}
    assert {r['status'] for r in meetings} == {'scheduled', 'canceled'}
    assert any(r['files'] == [] for r in materials)
    urls = {f['url'] for r in materials for f in r['files']}
    assert urls == {'https://example.org/hearing.pdf'}
    assert all(r['meeting_ids'] for r in materials)
    source_ids = {r['id'] for r in sources}
    assert all(set(r['source_ids']) <= source_ids for r in materials + meetings)
    assert any(json.loads(r['payload']).get('witnesses') for r in sources)
    info = json.loads((root/'queries.json').read_text())
    assert info['storage'] == 'parquet'
    assert 'payload' not in info['query_columns']
    assert pq.read_schema(root/'meetings.parquet').field('congress').type.bit_width == 32
    packaged, _ = package(tmp_path/'out', tmp_path/'browser')
    _, browser, _ = verify(tmp_path/'browser')
    assert (browser/'meetings.parquet').read_bytes() == (root/'meetings.parquet').read_bytes()
    assert all(not p.path.endswith('.data') for p in packaged.partitions)


def test_first_deployment_can_convert_gzipped_public_release(tmp_path):
    from committee_explorer.parquet import migrate
    source = write_meetings(tmp_path, [native()])
    _, catalog = export(meetings=source, output_dir=tmp_path/'legacy', state_dir=tmp_path/'state', as_of=NOW, format='json')
    package(tmp_path/'legacy', tmp_path/'compressed')
    migrate(tmp_path/'compressed', tmp_path/'converted')
    _, root, manifest = verify(tmp_path/'converted')
    meetings = pq.read_table(root/'meetings.parquet').to_pylist()
    assert {r['id'] for r in meetings} == {r.id for r in catalog.records if r.kind == 'meeting'}
    assert sum(p.record_count for p in manifest.partitions if p.role == 'sources') == len(catalog.sources)
    assert not list(root.rglob('*.data'))


def test_native_document_labels_and_event_video_wrapper(tmp_path):
    row = native()
    row['meetingDocuments'] = [{'description': 'Nominee questionnaire', 'documentType': 'Generic Document'}]
    row['witnessDocuments'] = [
        {'documentType': 'Witness Statement', 'format': 'PDF', 'url': 'https://example.org/statement.pdf'},
        {'documentType': 'Witness Truth in Testimony', 'format': 'PDF', 'url': 'https://example.org/disclosure.pdf'},
    ]
    event = 'https://www.congress.gov/event/115th-congress/house-event/106245'
    player = 'https://www.senate.gov/isvp/?comm=banking&filename=banking071217'
    row['videos'] = [{'url': event}, {'url': player}]
    _, catalog = export(meetings=write_meetings(tmp_path, [row]), output_dir=tmp_path/'out',
                        state_dir=tmp_path/'state', as_of=NOW, format='parquet')
    _, root, _ = verify(tmp_path/'out')
    records = pq.read_table(root/'materials.parquet').to_pylist()
    assert {r['title'] for r in records if r['type'] == 'document'} == {
        'Nominee questionnaire', 'Witness Statement', 'Witness Truth in Testimony'}
    assert next(r['category'] for r in records if r['title'] == 'Witness Truth in Testimony') == 'disclosure'
    recordings = [r for r in records if r['type'] == 'recording']
    assert len(recordings) == 1
    assert recordings[0]['recording_url'] == player
    assert recordings[0]['scheduled_at'] == row['date']
    assert catalog.sources[0].payload['videos'][0]['url'] == event
    assert all(not r['appearance_ids'] for r in records)  # Source supplies no witness ownership.


def test_folded_connections_keep_action_context_witness_ownership_and_all_formats(tmp_path):
    from committee_explorer.parquet import write_tables
    def ref(kind, id): return dict(kind=kind, id=id)
    records = [
        dict(kind='meeting', id='meeting'),
        dict(kind='appearance', id='witness', meeting=ref('meeting', 'meeting')),
        dict(kind='legislative_item', id='bill', item_type='bill', designation='H.R. 10'),
        dict(kind='meeting_subject', id='agenda', meeting=ref('meeting', 'meeting'), item=ref('legislative_item', 'bill')),
        dict(kind='amendment', id='amendment', meeting=ref('meeting', 'meeting'), number='7', target=ref('legislative_item', 'bill')),
        dict(kind='amendment_group', id='group', meeting=ref('meeting', 'meeting'), label='2', members=[ref('amendment', 'amendment')]),
        dict(kind='vote', id='vote', meeting=ref('meeting', 'meeting'), number='3', question='Adopt amendment 7', subject=ref('amendment', 'amendment')),
        dict(kind='vote', id='fileless', meeting=ref('meeting', 'meeting'), number='4', question='Report the bill'),
    ]
    queries = [dict(id='meeting', kind='meeting', title='Meeting'), dict(id='witness', kind='appearance', title='Witness')]
    for subject in ('amendment', 'vote', 'witness'):
        kind = 'appearance' if subject == 'witness' else subject
        id = subject + '-file'
        records += [dict(kind='material', id=id),
                    dict(kind='material_version', id=id+'-v', material=ref('material', id)),
                    dict(kind='material_link', id=id+'-link', material=ref('material', id), subject=ref(kind, subject))]
        queries.append(dict(kind='material', id=id, type='document', title='File'))
        for ext in ('pdf', 'xml'):
            records.append(dict(kind='representation', id=id+'-'+ext, version=ref('material_version', id+'-v'),
                                locations=[dict(url=f'https://example.org/{id}.{ext}', role='download')], format_label=ext))
    write_tables(iter(records), [], queries, tmp_path, lambda *args, **kwargs: None)
    materials = pq.read_table(tmp_path/'materials.parquet').to_pylist()
    assert all(r['meeting_ids'] == ['meeting'] and r['meeting_id'] == 'meeting' for r in materials)
    assert all(len(r['files']) == 2 for r in materials)
    assert next(r for r in materials if r['id'] == 'witness-file')['appearance_ids'] == ['witness']
    amendment = next(r for r in materials if r['id'] == 'amendment-file')
    assert {'label': 'Regarding', 'value': 'H.R. 10'} in amendment['facts']
    assert {'label': 'En bloc group', 'value': '2'} in amendment['facts']
    meeting = pq.read_table(tmp_path/'meetings.parquet').to_pylist()[0]
    assert {'label': 'Related bill', 'value': 'H.R. 10'} in meeting['facts']
    assert {'label': 'Vote 4', 'value': 'Report the bill (no attached file)'} in meeting['facts']


def test_retained_native_payload_repairs_old_untitled_rows_without_reassembly(tmp_path):
    from committee_explorer.parquet import write_tables
    citation = {'source': {'id': 'source'}, 'selector': '/witnessDocuments/0'}
    records = [{'kind': 'material', 'id': 'statement', 'provenance': {'citations': [citation]}}]
    sources = [{'kind': 'source_record', 'id': 'source', 'provider': 'congress.gov',
                'payload': {'witnessDocuments': [{'documentType': 'Witness Truth in Testimony'}]}}]
    queries = [{'kind': 'material', 'id': 'statement', 'title': '(Untitled source record)', 'type': 'document', 'category': 'statement'}]
    write_tables(records, sources, queries, tmp_path, lambda *args, **kwargs: None)
    material = pq.read_table(tmp_path/'materials.parquet').to_pylist()[0]
    assert material['title'] == 'Witness Truth in Testimony'
    assert material['category'] == 'disclosure'


@pytest.mark.parametrize('raw_type,title,expected', [
    ('Open Business Meeting', 'Budget consideration', 'business'),
    ('Closed Business Meeting', 'Budget consideration', 'business'),
    ('Meeting', 'Full Committee Business Meeting', 'business'),
    ('Markup', 'Full Committee Business Meeting', 'markup'),
    ('Field Hearing', 'Rural access', 'field_hearing'),
    ('Briefing', 'Current operations', 'briefing'),
    ('Meeting', 'Small business lending', 'unknown'),
])
def test_meeting_types_survive_adapter_and_retained_publication_conversion(tmp_path, raw_type, title, expected):
    from committee_explorer.parquet import migrate
    row = {**native(), 'type': raw_type, 'title': title}
    _, catalog = export(meetings=write_meetings(tmp_path, [row]), output_dir=tmp_path/'old', state_dir=tmp_path/'state', as_of=NOW)
    meeting = next(r for r in catalog.records if r.kind == 'meeting')
    assert meeting.meeting_type == expected
    assert bool(meeting.field_evidence) == (raw_type == 'Meeting' and expected == 'business')
    migrate(tmp_path/'old', tmp_path/'parquet')
    _, root, _ = verify(tmp_path/'parquet')
    exported = pq.read_table(root/'meetings.parquet').to_pylist()[0]
    assert exported['type'] == expected
    assert {'label': 'Source type', 'value': raw_type} in exported['facts']
