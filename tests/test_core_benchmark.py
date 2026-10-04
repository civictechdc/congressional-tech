"""Qualification compares records and schema, not merely equal row counts."""
import importlib.util
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('core_benchmark', ROOT / 'scripts/benchmark_core_rebuild.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_implementation_inventory_pins_runtime_rules_and_detects_added_files(tmp_path):
    rules = tmp_path / 'guide.json'
    rules.write_text('{"kind":"statement"}')
    committee = tmp_path / 'committees.csv'
    committee.write_text('code,name\nhsru00,Rules\n')
    before = benchmark.implementation_inventory([tmp_path])
    assert set(before) == {str(rules), str(committee)}
    rules.write_text('{"kind":"biography"}')
    assert benchmark.implementation_inventory([tmp_path]) != before
    before = benchmark.implementation_inventory([tmp_path])
    (tmp_path / 'new-rules.json').write_text('{}')
    assert benchmark.implementation_inventory([tmp_path]) != before


def test_canonical_records_ignore_row_order_but_preserve_all_evidence(tmp_path):
    schema = pa.schema([('document_id', pa.string()), ('aliases', pa.list_(pa.string())),
                        ('source_occurrences', pa.string()), ('classification', pa.string()),
                        ('failure', pa.string())])
    records = [dict(document_id='a', aliases=['x', 'y'], source_occurrences='[{"source":"senate"}]',
                    classification='witness-statement', failure=None),
               dict(document_id='b', aliases=[], source_occurrences='[]', classification=None, failure='404')]
    first, second = tmp_path / 'first.parquet', tmp_path / 'second.parquet'
    pq.write_table(pa.Table.from_pylist(records, schema=schema.with_metadata({'catalog_id': 'old'})), first)
    pq.write_table(pa.Table.from_pylist(records[::-1], schema=schema.with_metadata({'catalog_id': 'new'})), second)
    original = benchmark.canonical_table(first, tmp_path / 'a.sqlite')
    assert original == benchmark.canonical_table(second, tmp_path / 'b.sqlite')
    for case, (field, value) in enumerate([('document_id', 'changed'), ('aliases', ['x']), ('aliases', ['y', 'x']),
                         ('source_occurrences', '[]'), ('classification', None), ('failure', '403')]):
        changed = [dict(records[0], **{field: value}), records[1]]
        pq.write_table(pa.Table.from_pylist(changed, schema=schema), second)
        assert original != benchmark.canonical_table(second, tmp_path / (str(case) + field + '.sqlite'))


def test_overlay_reads_and_writes_leave_pinned_mirror_unchanged(tmp_path):
    mirror, output = tmp_path / 'mirror', tmp_path / 'output'
    (mirror / 'indexes').mkdir(parents=True)
    (mirror / 'indexes/a').write_bytes(b'original')
    before = benchmark.inventory(mirror)
    store = benchmark.MirrorOverlay(mirror, output)
    assert store.read('indexes/a') == b'original'
    store.put('indexes/a', b'candidate')
    assert store.read('indexes/a') == b'candidate'
    assert benchmark.inventory(mirror) == before
    assert store.reads == {'indexes': 2}
    assert store.read_bytes == {'indexes': 17}
    assert store.inputs_unchanged()
    (mirror / 'indexes/a').write_bytes(b'changed')
    assert not store.inputs_unchanged()


def test_input_pinning_detects_missing_objects_listings_and_repeated_read_changes(tmp_path):
    import pytest
    mirror = tmp_path / 'mirror'; mirror.mkdir()
    store = benchmark.MirrorOverlay(mirror, tmp_path / 'output')
    assert store.read('absent') is None
    (mirror / 'absent').write_bytes(b'new')
    assert not store.inputs_unchanged()
    with pytest.raises(RuntimeError, match='Pinned source changed'):
        store.read('absent')
    store = benchmark.MirrorOverlay(mirror, tmp_path / 'output')
    assert store.keys('') == ['absent']
    (mirror / 'added').write_bytes(b'new')
    assert not store.inputs_unchanged()
    with pytest.raises(RuntimeError, match='Pinned source listing changed'):
        store.keys('')
    store = benchmark.MirrorOverlay(mirror, tmp_path / 'output')
    assert store.version('absent') != 'missing'
    (mirror / 'absent').write_bytes(b'changed')
    assert not store.inputs_unchanged()


def test_rebuild_qualification_pins_inputs_and_checks_real_output_pair(tmp_path, monkeypatch):
    from congress_api.retention.raw_archive import Archive
    from congress_api.retention.catalog_publication import read_catalog
    from test_raw_source_sync import MemoryStore, response
    store = MemoryStore()
    archive = Archive(store, 'benchmark')
    archive.record(response('https://example.gov/report.pdf', b'%PDF-1.7\n%%EOF'), outcome='saved', links=[])
    archive.save()
    benchmark.rebuild_catalog(store, workers=1)
    snapshot = read_catalog(store)
    reference = tmp_path / 'reference'; reference.mkdir()
    (reference / 'document-filenames.parquet').write_bytes(snapshot.filenames)
    (reference / 'documents.parquet').write_bytes(snapshot.documents)
    mirror = tmp_path / 'mirror'
    for key, body in store.objects.items():
        path = mirror / key; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
    output = tmp_path / 'qualification'
    assert benchmark.main(['--mirror', str(mirror), '--reference', str(reference),
                           '--output', str(output), '--workers', '1', '--repair']) == 0
    import json
    report = json.loads((output / 'benchmark.json').read_text())
    assert report['status'] in {'passed', 'semantic_passed_memory_unqualified'}
    assert report['inputs_unchanged'] and report['semantic_equivalence_passed']
    assert report['source_inventory']['indexes/captures.parquet']['sha256']
    assert report['storage_reads']['indexes'] > 0
    assert report['stages'] and report['rebuild_memory']['process_peak_bytes'] > 0

    assert report['candidate_inventory']['documents.parquet']['sha256']
    assert report['candidate_manifest_inventory']['sha256']
    import pytest
    compare = benchmark.compare_tables
    for changed in ('reference', 'candidate'):
        saved = (reference / 'documents.parquet').read_bytes()
        def mutate(reference_path, candidate_paths, directory):
            result = compare(reference_path, candidate_paths, directory)
            path = reference_path / 'documents.parquet' if changed == 'reference' else candidate_paths['documents.parquet']
            path.write_bytes(b'changed during comparison')
            return result
        monkeypatch.setattr(benchmark, 'compare_tables', mutate)
        changed_output = tmp_path / ('changed-' + changed)
        with pytest.raises(RuntimeError, match='changed during comparison'):
            benchmark.main(['--mirror', str(mirror), '--reference', str(reference),
                            '--output', str(changed_output), '--workers', '1', '--repair'])
        failed = json.loads((changed_output / 'benchmark.json').read_text())
        assert failed['status'] == 'failed' and not failed['inputs_unchanged']
        (reference / 'documents.parquet').write_bytes(saved)
    monkeypatch.setattr(benchmark, 'compare_tables', compare)

    import os
    if os.environ.get('CORE_BENCHMARK_REPORT'):
        Path(os.environ['CORE_BENCHMARK_REPORT']).write_text(json.dumps(report, indent=2) + '\n')


def test_pair_comparison_reports_record_multiplicity_changes(tmp_path):
    reference = tmp_path / 'reference'; reference.mkdir()
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    comparison = tmp_path / 'comparison'; comparison.mkdir()
    paths = {}
    for name in ('document-filenames.parquet', 'documents.parquet'):
        pq.write_table(pa.table({'document_id': ['same', 'same']}), reference / name)
        pq.write_table(pa.table({'document_id': ['same', 'different']}), candidate / name)
        paths[name] = candidate / name
    result = benchmark.compare_tables(reference, paths, comparison)
    assert all(not table['equivalent'] for table in result.values())
    assert result['documents.parquet']['reference']['rows'] == result['documents.parquet']['candidate']['rows']
    assert result['documents.parquet']['mismatch_examples']['baseline'][0]['multiplicity'] == 2
    assert result['documents.parquet']['difference_counts'] == {
        'distinct_record_digests_with_different_multiplicity': 2,
        'reference_excess_rows': 1, 'candidate_excess_rows': 1}


def test_giant_records_use_fixed_size_scratch_and_bounded_examples(tmp_path):
    import sqlite3
    reference = tmp_path / 'reference'; reference.mkdir()
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    comparison = tmp_path / 'comparison'; comparison.mkdir()
    paths = {}
    for name in ('document-filenames.parquet', 'documents.parquet'):
        pq.write_table(pa.table({'document_id': ['a'], 'evidence': ['x' * (8 * 1024**2)]}), reference / name)
        pq.write_table(pa.table({'document_id': ['a'], 'evidence': ['y' * (8 * 1024**2)]}), candidate / name)
        paths[name] = candidate / name
    result = benchmark.compare_tables(reference, paths, comparison)
    for item in result.values():
        assert not item['equivalent']
        for side in ('baseline', 'candidate'):
            example = item['mismatch_examples'][side][0]
            assert example['row_ordinal'] == 0 and example['identifiers'] == {'document_id': 'a'}
            assert len(example['record_prefix']) == 2048
            assert example['record_characters'] > 8 * 1024**2
    for database in comparison.glob('*.sqlite'):
        assert database.stat().st_size < 256 * 1024
        with sqlite3.connect(database) as connection:
            assert connection.execute('SELECT length(digest) FROM records').fetchall() == [(32,)]
            plan = connection.execute('EXPLAIN QUERY PLAN SELECT digest, COUNT(*), MIN(ordinal) FROM records GROUP BY digest ORDER BY digest').fetchall()
            assert not any('TEMP B-TREE' in row[-1] for row in plan)


def test_comparison_recovery_pins_original_generation_and_rechecks_inputs(tmp_path, monkeypatch):
    import json
    import pytest
    from congress_api.retention import document_index as index
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog, publish_catalog
    reference = tmp_path / 'reference'; reference.mkdir()
    index.write_document_indexes(reference / 'document-filenames.parquet',
        [dict(body_key=None, filename='a.pdf', source_url='https://example.gov/a.pdf')], index.SOURCE_SCHEMA)
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    selected = publish_catalog(LocalStore(candidate), reference / 'document-filenames.parquet',
                               reference / 'documents.parquet', previous=read_catalog(LocalStore(candidate)))
    original = tmp_path / 'failed.json'
    original.write_text(json.dumps({'status': 'failed', 'error_type': 'OperationalError',
        'code_inventory': {'frozen.py': 'frozen-sha'}, 'result': selected,
        'reference_inventory': benchmark.inventory(reference)}))
    before = original.read_bytes()
    output = tmp_path / 'comparison'
    assert benchmark.main(['--compare-only', '--reference', str(reference), '--candidate-root', str(candidate),
                          '--original-report', str(original), '--output', str(output)]) == 0
    report = json.loads((output / 'comparison.json').read_text())
    assert report['status'] == 'semantic_equivalent' and report['inputs_unchanged']
    assert report['original_status'] == 'failed' and report['original_report_sha256'] == benchmark.digest_file(original)
    assert report['frozen_code_inventory'] == {'frozen.py': 'frozen-sha'}
    assert original.read_bytes() == before
    assert 'historical byte identity is unverified' in report['candidate_output_provenance']
    for field in ('catalog_id', 'generation'):
        altered = json.loads(before)
        altered['result'][field] = 'different'
        original.write_text(json.dumps(altered))
        with pytest.raises(ValueError, match='catalog_id'):
            benchmark.compare_only(reference, candidate, tmp_path / ('wrong-' + field), original)
        original.write_bytes(before)
    pinned_original = json.loads(before)
    pinned_original['candidate_inventory'] = {
        name: benchmark.file_properties(candidate / selected[key])
        for name, key in [('document-filenames.parquet', 'filenames_key'), ('documents.parquet', 'documents_key')]}
    pinned_original['candidate_manifest_inventory'] = benchmark.file_properties(candidate / selected['manifest_key'])
    original.write_text(json.dumps(pinned_original))
    pinned_report = benchmark.compare_only(reference, candidate, tmp_path / 'with-original-hashes', original)
    assert pinned_report['status'] == 'semantic_equivalent'
    assert 'Original candidate byte hashes matched' in pinned_report['candidate_output_provenance']
    original.write_bytes(before)
    altered = json.loads(before)
    altered['candidate_inventory'] = {name: {'sha256': 'wrong', 'bytes': 0}
                                     for name in ('document-filenames.parquet', 'documents.parquet')}
    original.write_text(json.dumps(altered))
    with pytest.raises(ValueError, match='Candidate bytes differ'):
        benchmark.compare_only(reference, candidate, tmp_path / 'wrong-hashes', original)
    original.write_bytes(before)
    compare = benchmark.compare_tables
    def mutate(*args):
        result = compare(*args)
        (reference / 'documents.parquet').write_bytes(b'changed')
        return result
    monkeypatch.setattr(benchmark, 'compare_tables', mutate)
    with pytest.raises(RuntimeError, match='Pinned comparison input'):
        benchmark.compare_only(reference, candidate, tmp_path / 'changed-comparison', original)
    failed = json.loads((tmp_path / 'changed-comparison/comparison.json').read_text())
    assert failed['status'] == 'failed' and not failed['inputs_unchanged']
    assert original.read_bytes() == before


def test_schema_comparison_preserves_field_metadata(tmp_path):
    path = tmp_path / 'table.parquet'
    def write(metadata):
        schema = pa.schema([pa.field('id', pa.string(), metadata=metadata)])
        pq.write_table(pa.Table.from_pylist([{'id': 'a'}], schema=schema), path)
    write({'evidence': 'x' * 10000 + 'a'})
    first = benchmark.canonical_table(path, tmp_path / 'first.sqlite')
    write({'evidence': 'x' * 10000 + 'b'})
    second = benchmark.canonical_table(path, tmp_path / 'second.sqlite')
    assert first['canonical_sha256'] == second['canonical_sha256']
    assert first['schema_sha256'] != second['schema_sha256']


def test_example_fetch_uses_batches_and_exact_late_ordinal(tmp_path, monkeypatch):
    path = tmp_path / 'large-group.parquet'
    pq.write_table(pa.table({'source_id': [f'row-{number}' for number in range(5000)]}), path, row_group_size=5000)
    original = pq.ParquetFile
    batches = []
    class TrackedParquet:
        def __init__(self, path):
            self.table = original(path)
            self.metadata = self.table.metadata
            self.num_row_groups = self.table.num_row_groups
        def iter_batches(self, **kwargs):
            assert kwargs['batch_size'] == 1024
            for batch in self.table.iter_batches(**kwargs):
                batches.append(batch.num_rows)
                yield batch
    monkeypatch.setattr(benchmark.pq, 'ParquetFile', TrackedParquet)
    example = benchmark.record_example(path, 4999, b'x' * 32, 2, 1)
    assert example['identifiers'] == {'source_id': 'row-4999'}
    assert example['row_ordinal'] == 4999 and len(batches) == 5
    assert example['record_prefix'] == '{"source_id":"row-4999"}'
