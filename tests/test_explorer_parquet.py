"""Verify browser tables against source-backed records, including missing links."""
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from committee_explorer.browser import package, verify
from committee_explorer.export import export
from test_explorer_export import native, write_meetings, NOW


def test_direct_committee_material_links_preserve_scope_and_lifecycle_without_meetings(tmp_path):
    from committee_explorer.parquet import write_tables
    source = dict(kind='source_record', id='source', provider='official-archive', payload={'committeeTypeCode': 'Other'})
    records = [
        dict(kind='committee_term', id='panel', committee_type='commission_or_caucus', source_committee_type='Other',
             active={'end': '2011-04-03'}, website='https://example.org/archive',
             provenance={'explanation': 'The panel concluded its work; retained documents remain available.'}),
        dict(kind='material', id='report'),
        dict(kind='material_link', id='link', material={'kind': 'material', 'id': 'report'}, subject={'kind': 'committee_term', 'id': 'panel'},
             provenance={'citations': [{'source': {'id': 'source'}}]}),
    ]
    queries = [dict(kind='committee_term', id='panel', title='Oversight Panel', congress=112, committee_ids=['panel']),
               dict(kind='material', id='report', title='Panel report', type='document', congress=112, committee_ids=['another'])]
    write_tables(records, [source], queries, tmp_path, lambda *a, **k: None)
    material = pq.read_table(tmp_path/'materials.parquet').to_pylist()[0]
    assert material['committee_ids'] == ['another', 'panel']
    assert material['meeting_ids'] == [] and material['meeting_id'] is None
    assert material['source_ids'] == ['source']
    assert material['committee_types'] == ['commission_or_caucus', 'unknown']
    assert pq.read_table(tmp_path/'meetings.parquet').num_rows == 0
    committee = pq.read_table(tmp_path/'committees.parquet').to_pylist()[0]
    assert committee['committee_type'] == 'commission_or_caucus'
    assert committee['source_committee_type'] == 'Other'
    assert committee['explanation'].startswith('The panel concluded its work')
    assert {'label': 'Active through', 'value': '2011-04-03'} in committee['facts']
    assert {'label': 'Official website or archive', 'value': 'https://example.org/archive'} in committee['facts']


def test_assembled_roundtable_keeps_native_hearing_as_source_evidence(tmp_path):
    from committee_explorer.parquet import write_tables
    source = dict(kind='source_record', id='source', provider='congress.gov', payload={'type': 'Hearing', 'title': 'Hearings to examine prediction markets'})
    meeting = dict(kind='meeting', id='meeting', meeting_type='roundtable',
                   provenance={'citations': [{'source': {'id': 'source'}}]})
    write_tables([meeting], [source], [dict(kind='meeting', id='meeting', type='roundtable', title='Prediction markets roundtable')],
                 tmp_path, lambda *a, **k: None)
    row = pq.read_table(tmp_path/'meetings.parquet').to_pylist()[0]
    assert row['type'] == 'roundtable'
    assert {'label': 'Source type', 'value': 'Hearing'} in row['facts']
    assert row['source_ids'] == ['source']
    assert json.loads(pq.read_table(tmp_path/'sources.parquet').to_pylist()[0]['payload']) == source['payload']


def test_issue_resolution_evidence_is_available_inline(tmp_path):
    from committee_explorer.parquet import write_tables
    issue = dict(kind='data_issue', id='issue', subject={'kind': 'meeting', 'id': 'meeting'},
                 provenance={'citations': [{'source': {'id': 'original'}}]},
                 resolution={'explanation': 'Reviewed collector labels.', 'decided_at': '2026-09-28T00:00:00Z',
                             'provenance': {'citations': [{'source': {'id': 'decision'}}]}})
    sources = [dict(kind='source_record', id=id, provider='test', payload={'id': id}) for id in ('original', 'decision')]
    queries = [dict(kind='meeting', id='meeting', title='Meeting'),
               dict(kind='data_issue', id='issue', title='Closed finding', status='dismissed')]
    write_tables([dict(kind='meeting', id='meeting'), issue], sources, queries, tmp_path, lambda *a, **k: None)
    published = pq.read_table(tmp_path/'issues.parquet').to_pylist()[0]
    assert published['source_ids'] == ['decision', 'original']
    assert {r['id'] for r in pq.read_table(tmp_path/'sources.parquet').to_pylist()} == {'decision', 'original'}


def test_committee_scope_uses_explicit_hierarchy_and_keeps_unknowns(tmp_path):
    from committee_explorer.parquet import write_tables
    terms = [dict(kind='committee_term', id='full', committee_type='standing'),
             dict(kind='committee_term', id='child', parent={'kind': 'committee_term', 'id': 'full'}),
             dict(kind='committee_term', id='other-child', committee_type='subcommittee'),
             dict(kind='committee_term', id='unknown', name='Committee on Rules', committee_type='unknown'),
             dict(kind='committee_term', id='coded-full', committee_type='standing', source_committee_type='Standing', identifiers=[{'scheme': 'congress.gov:committee', 'value': 'hsif00'}]),
             dict(kind='committee_term', id='coded-child', committee_type='subcommittee', source_committee_type='Subcommittee', identifiers=[{'scheme': 'congress.gov:committee', 'value': 'hsif03'}]),
             dict(kind='committee_term', id='task-force-child', committee_type='task_force', source_committee_type='Task Force', parent={'kind': 'committee_term', 'id': 'full'}, identifiers=[{'scheme': 'congress.gov:committee', 'value': 'hsta00'}])]
    records = terms + [dict(kind='meeting', id='meeting'), dict(kind='material', id='document'),
                       dict(kind='appearance', id='witness'),
                       dict(kind='data_issue', id='issue', subject={'kind': 'meeting', 'id': 'meeting'})]
    queries = [dict(kind='committee_term', id=r['id'], title=r['id'], committee_ids=[r['id']]) for r in terms]
    queries += [dict(kind='meeting', id='meeting', title='Joint hearing', committee_ids=['full', 'child']),
                dict(kind='material', id='document', title='Full committee document', type='document', committee_ids=['full']),
                dict(kind='appearance', id='witness', title='Witness', committee_ids=['other-child']),
                dict(kind='data_issue', id='issue', title='Issue', committee_ids=['unknown'], status='open')]
    write_tables(records, [], queries, tmp_path, lambda *a, **k: None)
    committees = {r['id']: r for r in pq.read_table(tmp_path/'committees.parquet').to_pylist()}
    assert {id: r['committee_level'] for id, r in committees.items()} == {
        'full': 'full', 'child': 'subcommittee', 'other-child': 'subcommittee', 'unknown': 'unknown',
        'coded-full': 'full', 'coded-child': 'subcommittee', 'task-force-child': 'subcommittee'}
    assert committees['child']['parent_committee_id'] == 'full'
    assert committees['coded-child']['parent_committee_id'] == 'coded-full'
    assert committees['coded-child']['source_committee_type'] == 'Subcommittee'
    assert committees['coded-child']['committee_type'] == 'subcommittee'
    assert committees['coded-child']['committee_types'] == ['standing']
    assert committees['other-child']['committee_types'] == ['unknown']
    assert committees['task-force-child']['committee_types'] == ['task_force']
    assert committees['task-force-child']['source_committee_type'] == 'Task Force'
    assert committees['task-force-child']['parent_committee_id'] == 'full'
    assert {'label': 'Committee hierarchy', 'value': 'The source identifies a parent committee.'} in committees['task-force-child']['facts']
    assert not any('00 identify a full committee' in f['value'] for f in committees['task-force-child']['facts'])
    assert any(f['label'] == 'Hierarchy definition' for f in committees['coded-child']['facts'])
    for table, level in [('meetings', 'subcommittee'), ('materials', 'full'), ('witnesses', 'subcommittee'), ('issues', 'unknown')]:
        assert pq.read_table(tmp_path/f'{table}.parquet').to_pylist()[0]['committee_level'] == level


def test_access_is_separate_from_meeting_type_and_survives_export(tmp_path):
    rows = [{**native(), 'eventId': str(106245+i), 'type': kind, 'title': title}
            for i, (kind, title) in enumerate([('Meeting', 'Closed briefing on readiness'),
                                             ('Open Hearing', 'School funding'),
                                             ('Meeting', 'Closed School Program: student outcomes')])]
    export(meetings=write_meetings(tmp_path, rows), output_dir=tmp_path/'out', state_dir=tmp_path/'state', as_of=NOW, format='parquet')
    _, root, _ = verify(tmp_path/'out')
    records = {r['title']: r for r in pq.read_table(root/'meetings.parquet').to_pylist()}
    assert (records['Closed briefing on readiness']['type'], records['Closed briefing on readiness']['access']) == ('briefing', 'closed')
    assert records['School funding']['access'] == 'open'
    assert records['Closed School Program: student outcomes']['access'] == 'unknown'
    assert {'label': 'Source type', 'value': 'Meeting'} in records['Closed briefing on readiness']['facts']
    assert any(f['label'] == 'Access based on' for f in records['Closed briefing on readiness']['facts'])
    assert 'access' in json.loads((root/'queries.json').read_text())['query_columns']


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
    assert {r['document_type'] for r in records if r['type'] == 'document'} == {'Generic Document', 'Witness Statement', 'Witness Truth in Testimony'}
    assert {r['title']: r['source_document_groups'] for r in records if r['type'] == 'document'} == {
        'Nominee questionnaire': ['meetingDocuments'], 'Witness Statement': ['witnessDocuments'],
        'Witness Truth in Testimony': ['witnessDocuments']}
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
    assert material['document_type'] == 'Witness Truth in Testimony'
    assert material['source_document_groups'] == ['witnessDocuments']


def test_shared_document_keeps_every_source_collection_without_inventing_witness_ownership(tmp_path):
    from committee_explorer.parquet import write_tables
    document = {'documentType': 'Witness Statement', 'url': 'https://example.org/statement.pdf'}
    citations = [{'source': {'id': 'source'}, 'selector': f'/{group}/0'} for group in ('meetingDocuments', 'witnessDocuments')]
    records = [dict(kind='material', id='statement', provenance=dict(citations=citations + citations))]
    sources = [dict(kind='source_record', id='source', provider='congress.gov',
                    payload=dict(meetingDocuments=[document], witnessDocuments=[document]))]
    queries = [dict(kind='material', id='statement', title='Statement', type='document')]
    write_tables(records, sources, queries, tmp_path, lambda *args, **kwargs: None)
    row = pq.read_table(tmp_path/'materials.parquet').to_pylist()[0]
    assert row['source_document_groups'] == ['meetingDocuments', 'witnessDocuments']
    assert row['document_type'] == 'Witness Statement'
    assert row['appearance_ids'] == []


def test_shared_bill_does_not_attach_other_meetings_as_source_evidence(tmp_path):
    from committee_explorer.parquet import write_tables
    def evidence(source): return dict(citations=[dict(source=dict(id=source))])
    records = [dict(kind='meeting', id='meeting', provenance=evidence('own')),
               dict(kind='legislative_item', id='bill', item_type='bill', designation='H.R. 10', provenance=evidence('other')),
               dict(kind='meeting_subject', id='agenda', meeting=dict(kind='meeting', id='meeting'),
                    item=dict(kind='legislative_item', id='bill'), provenance=evidence('own'))]
    sources = [dict(kind='source_record', id='own', provider='congress.gov', payload=dict(type='Meeting')),
               dict(kind='source_record', id='other', provider='congress.gov', payload=dict(type='Markup'))]
    write_tables(records, sources, [dict(kind='meeting', id='meeting', title='Current meeting')], tmp_path, lambda *args, **kwargs: None)
    row = pq.read_table(tmp_path/'meetings.parquet').to_pylist()[0]
    assert row['type'] == 'meeting'
    assert row['source_ids'] == ['own']
    assert {'label': 'Related bill', 'value': 'H.R. 10'} in row['facts']
    # Other meetings' source observations remain in the archive.
    assert set(pq.read_table(tmp_path/'sources.parquet', columns=['id'])['id'].to_pylist()) == {'own', 'other'}


@pytest.mark.parametrize('raw_type,title,expected', [
    ('Open Business Meeting', 'Budget consideration', 'business'),
    ('Closed Business Meeting', 'Budget consideration', 'business'),
    ('Meeting', 'Full Committee Business Meeting', 'business'),
    ('Markup', 'Full Committee Business Meeting', 'markup'),
    ('Field Hearing', 'Rural access', 'field_hearing'),
    ('Briefing', 'Current operations', 'briefing'),
    ('Meeting', 'Small business lending', 'meeting'),
    (None, 'Small business lending', 'unknown'),
    ('', 'Small business lending', 'unknown'),
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
    assert ({'label': 'Source type', 'value': raw_type} in exported['facts']) == bool(raw_type)


def test_conflicts_follow_folded_subjects_and_keep_competing_values(tmp_path):
    from committee_explorer.parquet import write_tables
    records = [
        dict(kind='meeting', id='meeting'),
        dict(kind='material', id='document'),
        dict(kind='material_version', id='version', material=dict(kind='material', id='document'), label='Revised statement',
             field_evidence=[dict(path='/label', alternatives=[dict(value='Original statement', provenance={})],
                                  selection_reason='Later source observation')]),
        dict(kind='data_issue', id='issue', subject=dict(kind='material_version', id='version'), field_path='/label'),
        dict(kind='assessment', id='check', subject=dict(kind='material', id='document')),
        dict(kind='data_issue', id='check-issue', subject=dict(kind='assessment', id='check')),
        dict(kind='appearance', id='witness', meeting=dict(kind='meeting', id='meeting'),
             affiliation=dict(position='Director', organization_name='Example Institute')),
    ]
    queries = [dict(kind='meeting', id='meeting', title='Hearing'),
               dict(kind='material', id='document', type='document', title='Statement'),
               dict(kind='data_issue', id='issue', title='Sources disagree about label', status='open'),
               dict(kind='data_issue', id='check-issue', title='Source check failed', status='open'),
               dict(kind='appearance', id='witness', title='Jane Smith')]
    write_tables(records, [], queries, tmp_path, lambda *args, **kwargs: None)
    issues = pq.read_table(tmp_path/'issues.parquet').to_pylist()
    assert all(i['subject_id'] == 'document' for i in issues)
    issue = next(i for i in issues if i['id'] == 'issue')
    assert (issue['subject_kind'], issue['subject_id']) == ('material', 'document')
    assert {'label':'Selected value', 'value':'Revised statement'} in issue['facts']
    assert {'label':'Alternative 1', 'value':'Original statement'} in issue['facts']
    assert pq.read_table(tmp_path/'materials.parquet').to_pylist()[0]['issue_count'] == 2
    witness = pq.read_table(tmp_path/'witnesses.parquet').to_pylist()[0]
    assert witness['search_text'] == 'Jane Smith Director Example Institute'


@pytest.mark.parametrize('status,expected', [('open', 'dismissed'), ('resolved', 'resolved')])
def test_collector_placeholders_are_not_open_source_conflicts(tmp_path, status, expected):
    from committee_explorer.parquet import write_tables
    records = [dict(kind='material',id='recording'),
               dict(kind='material_version',id='version',material=dict(kind='material',id='recording'),
                    label='Reported recording; revision not established', field_evidence=[dict(path='/label',
                    alternatives=[dict(value='Reported edition; revision not established',provenance={})])]),
               dict(kind='data_issue',id='issue',subject=dict(kind='material_version',id='version'),field_path='/label')]
    queries=[dict(kind='material',id='recording',type='recording',title='Video'),
             dict(kind='data_issue',id='issue',title='Sources disagree about label',status=status)]
    write_tables(records,[],queries,tmp_path,lambda *args,**kwargs:None)
    issue=pq.read_table(tmp_path/'issues.parquet').to_pylist()[0]
    assert issue['status']==expected
    if status == 'open': assert issue['title']=='Collector placeholder labels differed'
    assert any(f['label']=='Alternative 1' for f in issue['facts'])
    assert pq.read_table(tmp_path/'materials.parquet').to_pylist()[0]['issue_count']==0


@pytest.mark.parametrize('package,congress,category,source_type', [
    ('CHRG-109shrg25756', '109', 'supporting', 'Congressional Budget Justification'),
    ('CHRG-118hhrg55711', '118', 'committee_print', 'COMMITTEE PRINT'),
])
def test_reviewed_gpo_document_type_survives_without_replacing_category_or_title(tmp_path, package, congress, category, source_type):
    from committee_explorer.parquet import write_tables
    from congress_api.adapters import gpo
    from test_explorer_material_adapters import context, gpo_row
    records = list(gpo.records([gpo_row(package_id=package, congress=congress, title='Original package title')],
                              context(), review_context=context('gpo.committee-review')))
    material = next(r for r in records if r.kind == 'material')
    sources = [r.model_dump(mode='json') for r in records if r.kind == 'source_record']
    review = next(r for r in sources if r['provider'] == 'gpo.committee-review')
    # An unrelated observation must not leak its label into this document.
    sources.append(dict(kind='source_record', id='unrelated-review', provider='gpo.committee-review',
                        payload={'source_document_type': 'Different document'}))
    queries = [dict(kind='material', id=material.id, type='document', title=material.title, category=material.details.category)]
    write_tables((r.model_dump(mode='json') for r in records if r.kind != 'source_record'), sources, queries,
                 tmp_path, lambda *a, **k: None)
    published = pq.read_table(tmp_path/'materials.parquet').to_pylist()[0]
    assert published['title'] == 'Original package title'
    assert published['category'] == category
    assert published['document_type'] == source_type
    assert review['id'] in published['source_ids']
    published_sources = {r['id']: json.loads(r['payload']) for r in pq.read_table(tmp_path/'sources.parquet').to_pylist()}
    assert published_sources[review['id']]['source_document_type'] == source_type
    assert published_sources[review['id']]['source_urls']


def test_each_browser_table_has_its_own_schema_and_rejects_silent_data_loss(tmp_path):
    from committee_explorer.parquet import TABLE_SCHEMAS, write_tables
    assert 'files' in TABLE_SCHEMAS['material'].names
    assert 'appearance_ids' in TABLE_SCHEMAS['material'].names
    assert 'files' not in TABLE_SCHEMAS['appearance'].names
    assert 'position' not in TABLE_SCHEMAS['material'].names
    assert 'evidence_states' in TABLE_SCHEMAS['meeting'].names
    assert all('source_ids' in schema.names for schema in TABLE_SCHEMAS.values())
    with pytest.raises(ValueError, match='populated fields outside its table schema.*position'):
        write_tables([], [], [dict(kind='material', id='doc', title='Document', type='document', position='Must not disappear')],
                     tmp_path, lambda *a, **k: None)
