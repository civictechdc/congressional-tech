"""Verify browser tables against source-backed records, including missing links."""
import json
import subprocess
import sys
import tracemalloc

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from committee_explorer.browser import package, verify
from committee_explorer.export import export
from test_explorer_export import NOW, native, write_meetings


@pytest.mark.parametrize('count', [0, 1, 512, 1025])
def test_batched_parquet_preserves_file_bytes(tmp_path, count):
    import pyarrow as pa
    from committee_explorer.parquet import SOURCE_SCHEMA, _write_table

    rows = [dict(id=str(i), provider='test', payload=json.dumps({'text': 'évidence' * (i % 13)}))
            for i in range(count)]
    expected, actual = tmp_path / 'expected.parquet', tmp_path / 'actual.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=SOURCE_SCHEMA), expected,
                   compression='snappy', row_group_size=512, write_statistics=True)
    _write_table(rows, SOURCE_SCHEMA, actual, row_group_size=512)
    assert actual.read_bytes() == expected.read_bytes()


def test_parquet_source_conversion_has_bounded_arrow_memory(tmp_path):
    # A separate process gives Arrow a fresh allocation counter. Converting all
    # 32 MiB of payloads at once exceeds this budget; one row group fits easily.
    script = '''
import sys
import pyarrow as pa
from committee_explorer.parquet import _write_sources
rows = (dict(id=f'{i:05d}', payload='evidence' * 512) for i in range(8193))
_write_sources(rows, sys.argv[1])
print(pa.default_memory_pool().max_memory())
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)],
                            capture_output=True, text=True, check=True, timeout=30)
    assert int(result.stdout) < 16 * 1024 * 1024
    assert pq.read_metadata(tmp_path / 'sources.parquet').num_rows == 8193


def source(i, size=0):
    import random
    return dict(kind='source_record', id=f'{i:06d}', provider='test', url=f'https://example.org/{i}',
                identifier={'scheme': 'test:record', 'value': str(i)}, retained={'uri': f'sha256:{i}', 'sha256': str(i)},
                payload={'text': 'évidence' * (i % 13), 'noise': random.Random(i).randbytes(size).hex()})


def legacy_sources(sources, stage, *, limit=100_000_000, target=85_000_000):
    """The writer before streaming: collect every row, sort, split by row count."""
    from committee_explorer.parquet import SOURCE_SCHEMA, _source_row, _write_table
    rows = sorted((_source_row(s) for s in sources), key=lambda r: r['id'])
    _write_table(rows, SOURCE_SCHEMA, stage / 'sources.parquet', row_group_size=512)
    total = (stage / 'sources.parquet').stat().st_size
    if total < limit:
        return [('sources.parquet', len(rows))]
    (stage / 'sources.parquet').unlink()
    chunk = max(1, int(len(rows) * target / total))
    for i, start in enumerate(range(0, len(rows), chunk)):
        _write_table(rows[start:start + chunk], SOURCE_SCHEMA, stage / f'sources-{i + 1}.parquet', row_group_size=512)
    return [(f'sources-{i + 1}.parquet', len(rows[start:start + chunk])) for i, start in enumerate(range(0, len(rows), chunk))]


@pytest.mark.parametrize('count', [0, 1, 512, 1025])
def test_streamed_sources_keep_single_file_bytes_and_manifest_order(tmp_path, count):
    from committee_explorer.parquet import write_tables
    legacy, streamed = tmp_path / 'legacy', tmp_path / 'streamed'
    legacy.mkdir(), streamed.mkdir()
    sources = [source(i) for i in range(count)]
    expected = legacy_sources(reversed(sources), legacy)
    calls = []
    write_tables([], iter(sources), [], streamed, lambda path, role, schema, count, **kw: calls.append((path, role, count)))
    assert expected == [('sources.parquet', count)]
    assert [role for _, role, _ in calls] == ['details'] * 5 + ['sources']
    assert calls[-1] == ('sources.parquet', 'sources', count)
    assert (streamed / 'sources.parquet').read_bytes() == (legacy / 'sources.parquet').read_bytes()


def test_large_source_tables_stream_into_id_ordered_files_below_the_limit(tmp_path, monkeypatch):
    import pyarrow as pa
    from committee_explorer import parquet
    monkeypatch.setattr(parquet, 'SOURCE_FILE_TARGET', 200_000)
    monkeypatch.setattr(parquet, 'FILE_LIMIT', 240_000)
    legacy, streamed = tmp_path / 'legacy', tmp_path / 'streamed'
    legacy.mkdir(), streamed.mkdir()
    sources = [source(i, size=(i * 7919) % 300) for i in range(5000)]
    expected = legacy_sources(sources, legacy, limit=240_000, target=200_000)
    calls = []
    parquet.write_tables([], iter(sources), [], streamed,
                         lambda path, role, schema, count, **kw: calls.append((path, count)) if role == 'sources' else None)
    assert len(expected) > 1 and len(calls) > 1
    assert [path for path, _ in calls] == [f'sources-{i + 1}.parquet' for i in range(len(calls))]
    assert not (streamed / 'sources.parquet').exists()
    groups = []
    for path, count in calls:
        metadata = pq.read_metadata(streamed / path)
        assert metadata.num_rows == count
        assert (streamed / path).stat().st_size < 240_000
        groups += [metadata.row_group(i).num_rows for i in range(metadata.num_row_groups)]
    assert sum(count for _, count in calls) == 5000
    assert groups[:-1] == [512] * (len(groups) - 1)
    # Only file and row-group boundaries differ: same rows, order and schema.
    published = pa.concat_tables([pq.read_table(streamed / path) for path, _ in calls])
    assert published.equals(pa.concat_tables([pq.read_table(legacy / path) for path, _ in expected]), check_metadata=True)


@pytest.mark.parametrize('ids', [['b', 'a'], ['a', 'a']])
def test_sources_must_arrive_unique_and_in_id_order(tmp_path, ids):
    from committee_explorer.parquet import write_tables
    with pytest.raises(ValueError, match='ascending ID order'):
        write_tables([], [dict(kind='source_record', id=id, provider='test', payload={}) for id in ids], [],
                     tmp_path, lambda *a, **k: None)


def test_source_streaming_does_not_retain_serialized_payloads(tmp_path):
    from committee_explorer.parquet import write_tables

    def sources():  # 32 MiB of serialized payloads; one row group holds 4 MiB.
        for i in range(4096):
            yield dict(kind='source_record', id=f'{i:05d}', provider='test', payload={'text': 'evidence' * 1024})

    tracemalloc.start()
    try:
        write_tables([], sources(), [], tmp_path, lambda *a, **k: None)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 16 * 1024 * 1024
    assert pq.read_metadata(tmp_path / 'sources.parquet').num_rows == 4096


def test_catalog_sources_publish_in_id_order_whatever_the_catalog_order(tmp_path):
    from committee_meeting import Catalog
    from committee_explorer.parquet import write_catalog
    meetings = write_meetings(tmp_path, [native(), {**native(), 'eventId': '106246'}, {**native(), 'eventId': '106247'}])
    _, catalog = export(meetings=meetings, output_dir=tmp_path / 'parquet', state_dir=tmp_path / 'state', as_of=NOW, format='parquet')
    # apply_decisions appends its decision sources after the assembled order.
    unordered = Catalog.model_construct(sources=tuple(reversed(catalog.sources)), records=catalog.records)
    stage = tmp_path / 'stage'
    stage.mkdir()
    write_catalog(unordered, {(r.kind, r.id) for r in catalog.records}, stage, lambda *a, **k: None, lambda *a, **k: None, {})
    ids = pq.read_table(stage / 'sources.parquet', columns=['id'])['id'].to_pylist()
    assert len(ids) > 1 and ids == sorted(s.id for s in catalog.sources)


def source_record(i, size=0):
    import random
    from committee_meeting.common import Identifier
    from committee_meeting.provenance import SourceRecord
    return SourceRecord(id=f'{i:06d}', provider=f'test-{i % 3}', identifier=Identifier(scheme='test:record', value=str(i)),
                        url=f'https://example.org/{i}', payload={'text': 'évidence' * (i % 13), 'noise': random.Random(i).randbytes(size).hex()})


def release_files(root):
    _, directory, _ = verify(root)
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(directory.rglob('*')) if path.is_file()}


@pytest.mark.parametrize('file_target', [None, 60_000])
def test_retained_sources_merge_into_the_current_id_range_with_identical_bytes(tmp_path, monkeypatch, file_target):
    from committee_meeting import Catalog
    from committee_explorer import parquet
    if file_target:  # Several source files: boundaries depend only on the merged row stream.
        monkeypatch.setattr(parquet, 'SOURCE_FILE_TARGET', file_target)
    sources = [source_record(i, size=(i * 7919) % 200) for i in range(3000)]
    # Every third ID is a historical copy that issue history alone retains.
    current, retained = [s for i, s in enumerate(sources) if i % 3], [s for i, s in enumerate(sources) if not i % 3]
    written = {}
    for name, catalog, rest in (('in-memory', Catalog.model_construct(sources=tuple(sources), records=()), ()),
                                ('streamed', Catalog.model_construct(sources=tuple(reversed(current)), records=()), iter(retained))):
        stage = tmp_path / name
        stage.mkdir()
        calls = []
        parquet.write_catalog(catalog, set(), stage, lambda path, role, schema, count, **kw: calls.append((path, role, count)),
                              lambda *a, **k: None, {}, rest)
        written[name] = (calls, {p.name: p.read_bytes() for p in sorted(stage.iterdir())})
    assert written['streamed'] == written['in-memory']
    counts = [count for _, role, count in written['streamed'][0] if role == 'sources']
    assert sum(counts) == 3000 and (len(counts) > 1) == bool(file_target)


def deterministic_ids(monkeypatch, seed):
    """Two exports from copies of one state allocate the same new persistent IDs."""
    import random
    import uuid
    from committee_explorer import ids
    generator = random.Random(seed)
    monkeypatch.setattr(ids, 'uuid4', lambda: uuid.UUID(int=generator.getrandbits(128), version=4))


def in_memory_finish(finish):
    """Assembly before history sources stayed on disk: every one loads into the catalog."""
    from committee_meeting import Catalog
    from committee_explorer.history import RetainedSources
    def load_retained(self):
        catalog = finish(self)
        for key in self.retained:
            self.sources[key] = self.retained[key]
        self.retained = RetainedSources()
        return Catalog.model_construct(sources=tuple(self.sources[k] for k in sorted(self.sources)),
                                       records=catalog.records).check_graph()
    return load_retained


@pytest.mark.parametrize('format', ['parquet'])
def test_history_sources_publish_exactly_as_when_loaded_in_memory(tmp_path, monkeypatch, format):
    """Every input snapshot re-keys its sources; old issues keep citing the old ones.

    The streamed export must publish the same files, manifest (retained input
    snapshots, coverage counts) and issue history as the in-memory catalog did.
    """
    import gzip
    import shutil
    import sqlite3
    from committee_explorer.assemble import Assembly
    rows = [{**native(), 'eventId': str(106245 + i), 'date': 'invalid date'} for i in range(12)]
    def run(root, generation, **kwargs):
        meetings = tmp_path / f'meetings-{generation}.jsonl.gz'  # Same rows, new snapshot bytes.
        meetings.write_bytes(gzip.compress(b'\n'.join(json.dumps(r).encode() for r in rows), mtime=generation))
        return export(meetings=meetings, output_dir=root / 'public', state_dir=root / 'state',
                      as_of=NOW.replace(day=20 + generation), format=format, **kwargs)
    deterministic_ids(monkeypatch, 1)
    _, first = run(tmp_path / 'previous', 1)
    decisions = tmp_path / 'decisions.json'
    issue = next(r for r in first.records if r.kind == 'data_issue')
    decisions.write_text(json.dumps([{'issue_id': issue.id, 'status': 'dismissed', 'explanation': 'Reviewed.'}]))
    for name in ('in-memory', 'streamed'):
        shutil.copytree(tmp_path / 'previous', tmp_path / name)
    original = Assembly.finish
    for generation in (2, 3):  # 2 records a new decision; 3 replays it from history.
        results = {}
        for name in ('in-memory', 'streamed'):
            deterministic_ids(monkeypatch, generation)
            monkeypatch.setattr(Assembly, 'finish', in_memory_finish(original) if name == 'in-memory' else original)
            manifest, catalog = run(tmp_path / name, generation, issue_decisions=decisions)
            with sqlite3.connect(next((tmp_path / name / 'state/issue-history').glob('*.sqlite'))) as connection:
                digest = connection.execute("SELECT value FROM metadata WHERE key='content_sha256'").fetchone()
            state = {path: (tmp_path / name / 'state' / path).read_bytes() for path in ('ids.json', 'publication.json')}
            results[name] = (release_files(tmp_path / name / 'public'), digest, state, catalog)
        assert results['streamed'][:3] == results['in-memory'][:3]
        # The case is real: retained sources interleave with current ones by ID.
        files, _, _, catalog = results['streamed']
        if format == 'parquet':
            published = [row for path in sorted(files) if path.startswith('sources')
                         for row in pq.read_table(pa.BufferReader(files[path]), columns=['id', 'input_snapshot_id']).to_pylist()]
        else:
            published = json.loads(files['catalog.json'])['sources']
        decision_sources = [s.id for s in catalog.sources if s.provider == 'curated-issue-decisions']
        assert bool(decision_sources) == (generation == 2)  # Generation 3 reuses the retained observation.
        # Parquet sorts every source; catalog.json keeps a new decision source last, as before.
        ids = [row['id'] for row in published]
        tail = decision_sources if format == 'json' else []
        head = ids[:len(ids) - len(tail)]
        assert head == sorted(head) and ids[len(head):] == tail
        current = {s.id for s in catalog.sources}
        retained = {row['id']: row['input_snapshot_id'] for row in published if row['id'] not in current}
        assert current and retained and current <= {row['id'] for row in published}
        assert any(min(current) < id < max(current) for id in retained)
        # Snapshots of earlier generations stay in the manifest for retained sources only.
        assert set(retained.values()) <= {s.id for s in manifest.inputs} - {s.input_snapshot_id for s in catalog.sources}


def test_file_link_building_does_not_retain_complete_representation_payloads(tmp_path):
    from committee_explorer.parquet import write_tables

    def records():
        yield dict(kind='material', id='document')
        yield dict(kind='material_version', id='version', material={'id': 'document', 'kind': 'material'})
        for i in range(1000):
            yield dict(kind='representation', id=str(i), version={'id': 'version', 'kind': 'material_version'},
                       media_type='application/pdf', locations=[{'url': f'https://example.org/{i}.pdf', 'role': 'download'}],
                       provenance={'explanation': str(i) + 'evidence ' * 8192,
                                   'citations': [{'source': {'id': 'source'}}]})

    tracemalloc.start()
    try:
        write_tables(records(), [], [dict(kind='material', id='document', type='document')],
                     tmp_path, lambda *a, **k: None)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 16 * 1024 * 1024
    row = pq.read_table(tmp_path / 'materials.parquet').to_pylist()[0]
    assert len(row['files']) == 1000
    assert row['source_ids'] == ['source']


def test_saved_copy_fields_follow_the_file_into_the_browser_table(tmp_path):
    from committee_explorer.parquet import write_tables
    digest = 'ab' * 32
    records = [dict(kind='material', id='statement'),
               dict(kind='material_version', id='edition', material=dict(kind='material', id='statement')),
               dict(kind='representation', id='pdf', version=dict(kind='material_version', id='edition'),
                    format_label='PDF', media_type='application/pdf', saved_copy_sha256=digest, saved_filename='Witness statement.pdf',
                    locations=[dict(url='https://example.org/statement.pdf', role='download')])]
    write_tables(records, [], [dict(kind='material', id='statement', title='Statement', type='document')],
                 tmp_path, lambda *args, **kwargs: None)
    file, = pq.read_table(tmp_path/'materials.parquet').to_pylist()[0]['files']
    assert file['url'] == 'https://example.org/statement.pdf'
    assert (file['saved_copy_sha256'], file['saved_filename']) == (digest, 'Witness statement.pdf')


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
    meeting = dict(kind='meeting', id='meeting', meeting_type='roundtable', source_type='Hearing',
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
    sources = [dict(kind='source_record', id=id, provider='test', payload={'id': id}) for id in ('decision', 'original')]
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


@pytest.mark.parametrize('raw_type,title,kind,access', [
    ('Meeting', 'A briefing on the annual budget', 'briefing', 'unknown'),
    ('Meeting', 'To receive a closed briefing on intelligence', 'briefing', 'closed'),
    ('Hearing', 'Open Borders, Closed Case: oversight', 'hearing', 'unknown'),
    ('Meeting', 'Business Meeting (Open in a Closed Space)', 'business', 'open'),
    ('Meeting', 'Small business lending', 'meeting', 'unknown'),
    ('Meeting', 'Open and closed hearings to examine worldwide threats', 'hearing', 'partly_closed'),
    ('Field Hearing', 'Rural access', 'field_hearing', 'unknown'),
    ('Roundtable', 'Housing supply', 'roundtable', 'unknown'),
    ('Markup', 'Full Committee Business Meeting', 'markup', 'unknown'),
    ('Hearing', 'Markup of the annual budget', 'hearing', 'unknown'),
])
def test_inventory_adapter_and_browser_use_the_same_meeting_rules(tmp_path, raw_type, title, kind, access):
    from congress_api.matching import completeness
    from congress_api.matching import recordings as text_sources

    row = {**native(), 'type': raw_type, 'title': title}
    index = {r['event_id']: r for r in text_sources.build([row], [], [], [], [], [], {}, {}, {})}
    inventory, _ = completeness.build([row], index, [], [], [], {}, {}, {}, {})
    assert inventory[0]['kind'] == kind
    assert inventory[0]['access'] == access
    assert inventory[0]['closed'] == ('yes' if access == 'closed' else '')
    _, catalog = export(meetings=write_meetings(tmp_path, [row]), output_dir=tmp_path/'public',
                        state_dir=tmp_path/'state', as_of=NOW, format='parquet')
    assert next(r for r in catalog.records if r.kind == 'meeting').meeting_type == kind
    assert next(r for r in catalog.records if r.kind == 'occurrence').access == access
    _, root, _ = verify(tmp_path/'public')
    published, = pq.read_table(root/'meetings.parquet').to_pylist()
    assert (published['type'], published['access']) == (kind, access)
    source = next(s for s in catalog.sources if s.provider == 'congress.gov' and s.payload.get('eventId') == row['eventId'])
    assert source.payload == row


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


def test_legacy_json_format_is_rejected_and_parquet_is_default(tmp_path):
    source = write_meetings(tmp_path, [native()])
    with pytest.raises(ValueError, match='requires parquet'):
        export(meetings=source, output_dir=tmp_path/'legacy', state_dir=tmp_path/'state', as_of=NOW, format='json')
    manifest, catalog = export(meetings=source, output_dir=tmp_path/'parquet', state_dir=tmp_path/'state', as_of=NOW)
    _, root, _ = verify(tmp_path/'parquet')
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


def test_untitled_material_falls_back_to_category_and_keeps_stored_fields(tmp_path):
    from committee_explorer.parquet import write_tables
    citation = {'source': {'id': 'source'}, 'selector': '/witnessDocuments/0'}
    records = [{'kind': 'material', 'id': 'statement', 'document_type': 'Witness Truth in Testimony',
                'source_document_groups': ['witnessDocuments'], 'provenance': {'citations': [citation]}}]
    sources = [{'kind': 'source_record', 'id': 'source', 'provider': 'congress.gov',
                'payload': {'witnessDocuments': [{'documentType': 'Witness Truth in Testimony'}]}}]
    queries = [{'kind': 'material', 'id': 'statement', 'title': '(Untitled source record)', 'type': 'document', 'category': 'disclosure'}]
    write_tables(records, sources, queries, tmp_path, lambda *args, **kwargs: None)
    material = pq.read_table(tmp_path/'materials.parquet').to_pylist()[0]
    assert material['title'] == 'Disclosure'
    assert material['category'] == 'disclosure'
    assert material['document_type'] == 'Witness Truth in Testimony'
    assert material['source_document_groups'] == ['witnessDocuments']


def test_shared_document_keeps_every_source_collection_without_inventing_witness_ownership(tmp_path):
    from committee_explorer.parquet import write_tables
    document = {'documentType': 'Witness Statement', 'url': 'https://example.org/statement.pdf'}
    citations = [{'source': {'id': 'source'}, 'selector': f'/{group}/0'} for group in ('meetingDocuments', 'witnessDocuments')]
    records = [dict(kind='material', id='statement', document_type='Witness Statement',
                    source_document_groups=['meetingDocuments', 'witnessDocuments'],
                    provenance=dict(citations=citations + citations))]
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
    records = [dict(kind='meeting', id='meeting', meeting_type='meeting', provenance=evidence('own')),
               dict(kind='legislative_item', id='bill', item_type='bill', designation='H.R. 10', provenance=evidence('other')),
               dict(kind='meeting_subject', id='agenda', meeting=dict(kind='meeting', id='meeting'),
                    item=dict(kind='legislative_item', id='bill'), provenance=evidence('own'))]
    sources = [dict(kind='source_record', id='other', provider='congress.gov', payload=dict(type='Markup')),
               dict(kind='source_record', id='own', provider='congress.gov', payload=dict(type='Meeting'))]
    write_tables(records, sources, [dict(kind='meeting', id='meeting', title='Current meeting', type='meeting')], tmp_path, lambda *args, **kwargs: None)
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
def test_meeting_types_survive_adapter_and_parquet_export(tmp_path, raw_type, title, expected):
    row = {**native(), 'type': raw_type, 'title': title}
    _, catalog = export(meetings=write_meetings(tmp_path, [row]), output_dir=tmp_path/'parquet', state_dir=tmp_path/'state', as_of=NOW)
    meeting = next(r for r in catalog.records if r.kind == 'meeting')
    assert meeting.meeting_type == expected
    assert bool(meeting.field_evidence) == (raw_type == 'Meeting' and expected == 'business')
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
    write_tables((r.model_dump(mode='json') for r in records if r.kind != 'source_record'),
                 sorted(sources, key=lambda s: s['id']), queries, tmp_path, lambda *a, **k: None)
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


def test_committee_source_types_and_witness_ownership_survive_parquet(tmp_path):
    from committee_explorer.parquet import write_tables
    url = 'https://example.org/testimony'
    selector = '/document_metadata/' + url.replace('~', '~0').replace('/', '~1')
    sources = [dict(kind='source_record', id='house', provider='docs.house.gov', payload={
        'evidence': {'document_groups': [{'type': 'WT', 'source': 'witness_xml'}]}}),
        dict(kind='source_record', id='senate', provider='senate.committees', payload={
            'document_metadata': {url: {'labels': ['Download Testimony'], 'witness_indexes': [0]}}})]
    records = [dict(kind='material', id='house-doc', document_type='Truth in testimony',
                    source_document_groups=['Witness documents'],
                    details={'type': 'document', 'category': 'disclosure'},
                    provenance={'citations': [{'source': {'id': 'house'}, 'selector': '/evidence/document_groups/0'}]}),
               dict(kind='material', id='senate-doc', source_document_groups=['Witness documents'],
                    details={'type': 'document', 'category': 'statement'},
                    provenance={'citations': [{'source': {'id': 'senate'}, 'selector': selector}]})]
    queries = [dict(kind='material', id=r['id'], title=r['id'], type='document') for r in records]
    write_tables(records, sources, queries, tmp_path, lambda *a, **k: None)
    rows = {r['id']: r for r in pq.read_table(tmp_path/'materials.parquet').to_pylist()}
    assert rows['house-doc']['document_type'] == 'Truth in testimony'
    assert rows['house-doc']['source_document_groups'] == ['Witness documents']
    assert rows['senate-doc']['document_type'] is None  # A link label is not a reported document type.
    assert rows['senate-doc']['source_document_groups'] == ['Witness documents']


def test_carried_house_fields_are_copied_once(tmp_path):
    from committee_explorer.parquet import write_tables
    sources = [dict(kind='source_record', id='house', provider='docs.house.gov', payload={
        'evidence': {'document_groups': [{'type': 'WT', 'source': 'witness_xml'}]}})]
    records = [dict(kind='material', id='house-doc', document_type='Truth in testimony',
                     source_document_groups=['Witness documents'],
                     provenance={'citations': [{'source': {'id': 'house'}, 'selector': '/evidence/document_groups/0'}]})]
    queries = [dict(kind='material', id='house-doc', title='Form', type='document')]
    write_tables(records, sources, queries, tmp_path, lambda *args, **kwargs: None)
    row = pq.read_table(tmp_path / 'materials.parquet').to_pylist()[0]
    assert row['document_type'] == 'Truth in testimony'
    assert row['source_document_groups'] == ['Witness documents']
    assert not any(fact['label'] == 'Source document type code' for fact in row['facts'])


def test_meeting_start_wins_over_an_earlier_occurrence(tmp_path):
    from committee_explorer.parquet import write_tables
    records = [
        dict(kind='meeting', id='meeting', scheduled_start={'date': '2026-09-02', 'original': '2026-09-02T15:00:00Z'}),
        dict(kind='occurrence', id='earlier', meeting={'kind': 'meeting', 'id': 'meeting'},
             scheduled_start={'date': '2026-09-01', 'original': '2026-09-01T15:00:00Z'}),
    ]
    write_tables(records, [], [dict(kind='meeting', id='meeting', title='Hearing')], tmp_path, lambda *args, **kwargs: None)
    assert pq.read_table(tmp_path / 'meetings.parquet').to_pylist()[0]['scheduled_at'] == '2026-09-02T15:00:00Z'


def test_stored_committee_code_and_level_are_copied(tmp_path):
    from committee_explorer.parquet import write_tables
    records = [dict(kind='committee_term', id='coded', committee_code='hsif03', committee_level='full',
                    identifiers=[{'scheme': 'congress.gov:committee', 'value': 'hsif00'}])]
    write_tables(records, [], [dict(kind='committee_term', id='coded', title='Coded')], tmp_path, lambda *args, **kwargs: None)
    row = pq.read_table(tmp_path / 'committees.parquet').to_pylist()[0]
    assert (row['committee_code'], row['committee_level']) == ('hsif03', 'full')
    assert row['parent_committee_id'] is None


def test_carried_senate_witness_group_keeps_an_empty_document_type(tmp_path):
    from committee_explorer.parquet import write_tables
    url = 'https://example.org/testimony'
    selector = '/document_metadata/' + url.replace('~', '~0').replace('/', '~1')
    sources = [dict(kind='source_record', id='senate', provider='senate.committees', payload={
        'document_metadata': {url: {'labels': ['Download Testimony'], 'witness_indexes': [0]}}})]
    records = [dict(kind='material', id='senate-doc', source_document_groups=['Witness documents'],
                     provenance={'citations': [{'source': {'id': 'senate'}, 'selector': selector}]})]
    write_tables(records, sources, [dict(kind='material', id='senate-doc', title='Testimony', type='document')],
                 tmp_path, lambda *args, **kwargs: None)
    row = pq.read_table(tmp_path / 'materials.parquet').to_pylist()[0]
    assert row['document_type'] is None
    assert row['source_document_groups'] == ['Witness documents']
    assert not any(fact['label'] == 'Source link label' for fact in row['facts'])
