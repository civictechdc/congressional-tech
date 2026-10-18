"""Byte admission, exact streaming reconstruction and explicit count custody."""
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from filename_budget import (DEFAULT_DECODED_POLICY, DecodedBudgetExceeded, bounded_batches,
                             json_chunks, plan_native_rows, open_parquet, python_estimate)
from filename_json_stream import ObservationCounts, block_items, decoded_json_default
import filename_details as details
import filename_observations as observations

spec = importlib.util.spec_from_file_location('budget_publication',
    Path(__file__).resolve().parents[1] / 'apps/site/scripts/publish-filename-viewer.py')
publisher = importlib.util.module_from_spec(spec); spec.loader.exec_module(publisher)


def source_file(folder, rows):
    schema = pa.schema([('filename', pa.string()), ('body_key', pa.string()),
        ('source_page_title', pa.list_(pa.string())), ('state_checked_at', pa.list_(pa.string())),
        ('content_labels', pa.list_(pa.string())), ('wording', pa.list_(pa.string())),
        ('http_status', pa.list_(pa.string())), ('response_usable', pa.list_(pa.string())),
        ('response_body_complete', pa.list_(pa.string())),
        ('source_occurrences', pa.list_(pa.struct([('label', pa.list_(pa.string()))])))],
        metadata={b'catalog_id': b'budget-fixture'})
    path = folder / 'source.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path, row_group_size=3)
    return path


def test_adaptive_batches_bound_admitted_arrow_and_allow_explicit_single_row(tmp_path):
    path = source_file(tmp_path, [{'filename': '🏛️' * 1000}] + [{'filename': str(i)} for i in range(9)])
    policy = replace(DEFAULT_DECODED_POLICY, batch_arrow_bytes=256, batch_python_estimate=4096)
    metrics = {}
    with pq.ParquetFile(path) as source:
        batches = list(bounded_batches(source, columns=['filename'], policy=policy, metrics=metrics))
    assert [row['filename'] for b in batches for row in b.to_pylist()] == ['🏛️' * 1000] + list(map(str, range(9)))
    assert all(len(b) == 1 or b.nbytes <= 256 for b in batches)
    assert metrics['oversized_rows_admitted'] > 0


def footer_group(rows, columns):
    from types import SimpleNamespace
    chunks = [SimpleNamespace(path_in_schema=path, total_uncompressed_size=size) for path, size in columns]
    return SimpleNamespace(num_rows=rows, num_columns=len(chunks), column=chunks.__getitem__)


def test_retained_real_footer_shape_plans_rows_without_aggregate_refusal():
    # Exact retained rebuilt-documents group389 shape, no real-data decode.
    group = footer_group(1024, [('source_occurrences.list.element.source_link_label.list.element', 89688776),
                                ('source_link_label.list.element', 72737052), ('other', 1486603)])
    metrics = {}
    assert plan_native_rows(group, metrics=metrics) == 26
    assert metrics['max_physical_group_bytes'] == 163912431
    assert plan_native_rows(group, batch_rows=7) == 7
    assert plan_native_rows(footer_group(1, [('huge', 10**12)])) == 1
    assert plan_native_rows(footer_group(0, [])) == 1


def test_planner_matches_nested_prefixes_once_and_distinguishes_empty_projection():
    group = footer_group(1024, [('source_occurrences.list.element.label.list.element', 163912431),
        ('source_occurrences.list.element.label_extra.list.element', 8192), ('filename', 4096)])
    metrics = {}
    assert plan_native_rows(group, columns=['source_occurrences.list.element.label'], metrics=metrics) == 26
    assert metrics['max_physical_group_bytes'] == 163912431
    for columns, expected in [(None, 163924719), ([], 0), (['filename'], 4096),
        (['source_occurrences', 'source_occurrences.list.element.label'], 163920623)]:
        metrics = {}; plan_native_rows(group, columns=columns, metrics=metrics)
        assert metrics['max_physical_group_bytes'] == expected


def test_native_calls_use_each_groups_plan_and_return_all_rows(tmp_path):
    batch = pa.record_batch([['value']], names=['filename'])
    groups = [footer_group(1024, [('filename', 163912431)]), footer_group(1024, [('filename', 4096)])]
    class Metadata:
        num_row_groups = 2
        def row_group(self, index): return groups[index]
    class Source:
        metadata = Metadata()
        calls = []
        def iter_batches(self, **kwargs): self.calls.append(kwargs); return iter([batch])
    source = Source()
    assert [b.column(0)[0].as_py() for b in bounded_batches(source)] == ['value', 'value']
    assert [call['batch_size'] for call in source.calls] == [26, 128]
    assert [call['row_groups'] for call in source.calls] == [[0], [1]]
    assert all(call['use_threads'] is False for call in source.calls)


def test_large_physical_group_of_small_rows_repacks_with_full_value_verification(tmp_path):
    path = tmp_path / 'large-group.parquet'
    # A real >64MiB uncompressed physical group, with individually small rows.
    table = pa.table({'value': pa.repeat(pa.scalar('é' * 512), 65536)})
    pq.write_table(table, path, row_group_size=65536, use_dictionary=False, compression='zstd')
    del table
    with pq.ParquetFile(path) as source:
        assert source.metadata.row_group(0).column(0).total_uncompressed_size > 64 * 1024**2
    metrics = {}
    result = publisher.repack_and_verify(path, tmp_path / 'repacked.parquet', metrics=metrics)
    assert result['rows'] == 65536 and result['exact_equal'] is True
    assert metrics['max_physical_group_bytes'] > 64 * 1024**2
    assert metrics['max_native_batch_rows'] <= 128
    assert metrics['max_batch_arrow_bytes'] <= DEFAULT_DECODED_POLICY.batch_arrow_bytes


def test_empty_projection_and_empty_parquet_preserve_source_row_count(tmp_path):
    path = tmp_path / 'empty.parquet'
    pq.write_table(pa.table({'value': pa.array([], type=pa.string())}), path)
    assert publisher.repack_and_verify(path, tmp_path / 'empty-copy.parquet')['rows'] == 0
    with pq.ParquetFile(path) as source:
        assert sum(len(batch) for batch in bounded_batches(source, columns=[])) == 0
    nonempty = tmp_path / 'nonempty.parquet'
    pq.write_table(pa.table({'value': ['one', 'two', 'three']}), nonempty)
    with pq.ParquetFile(nonempty) as source:
        projected = list(bounded_batches(source, columns=[]))
        assert sum(len(batch) for batch in projected) == 3
        assert all(batch.num_columns == 0 for batch in projected)


def test_repack_borrows_original_reader_without_reopening_or_closing_it(tmp_path, monkeypatch):
    path = source_file(tmp_path, [{'filename': 'one'}, {'filename': 'two'}])
    original = publisher.open_parquet; opened = []
    def opening(candidate):
        assert candidate != path, 'borrowed input footer reopened'
        opened.append(candidate); return original(candidate)
    monkeypatch.setattr(publisher, 'open_parquet', opening)
    with open_parquet(path) as source:
        metadata = source.metadata
        assert publisher.repack_and_verify(source, tmp_path / 'copy.parquet')['exact_equal']
        assert source.metadata is metadata and source.read().num_rows == 2
    assert opened == [tmp_path / 'copy.parquet']


def test_preparation_readers_disable_readahead_and_buffer_column_reads(monkeypatch):
    import filename_budget
    calls = []
    monkeypatch.setattr(filename_budget.pq, 'ParquetFile', lambda *args, **kwargs: calls.append((args, kwargs)))
    filename_budget.open_parquet('owned.parquet')
    assert calls == [(('owned.parquet',), {'pre_buffer': False, 'buffer_size': 65536})]


@pytest.mark.parametrize('limit', ['row_arrow_bytes', 'row_python_estimate', 'logical_json_bytes'])
def test_oversized_values_refuse_without_truncating_or_accepting_source(tmp_path, limit):
    path = source_file(tmp_path, [{'source_occurrences': [{'label': ['🏛️' * 10000]}]}])
    original = hashlib.sha256(path.read_bytes()).hexdigest()
    policy = replace(DEFAULT_DECODED_POLICY, **{limit: 1024})
    with pq.ParquetFile(path) as source, pytest.raises(DecodedBudgetExceeded, match='source retained'):
        observations.publish_observations(source, tmp_path, policy=policy)
    receipt = json.loads((tmp_path / 'preparation-memory-failure.json').read_text())
    assert receipt['status'] == 'refused' and receipt['source_preserved']
    assert not receipt['partial_publication_accepted']
    assert not (tmp_path / 'observation-index.json').exists()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original


def test_count_handoff_requires_source_identity_and_complete_unchanged_rows(tmp_path):
    path = source_file(tmp_path, [{'filename': 'one'}, {'filename': 'two'}])
    with pq.ParquetFile(path) as source, pq.ParquetFile(path) as other, ObservationCounts(source) as counts:
        counts.append(0)
        with pytest.raises(ValueError, match='source rows'): counts.seal(2)
        counts.append(1); counts.seal(2)
        with pytest.raises(ValueError, match='this source'): list(counts.values(other))
        assert list(counts.values(source)) == [0, 1]
        counts.stream.seek(0); counts.stream.write(struct.pack('<Q', 1))
        with pytest.raises(ValueError, match='changed'): list(counts.values(source))


@pytest.mark.parametrize('kind', ['missing', 'trailing', 'changed'])
def test_details_reject_count_corruption_before_output_acceptance(tmp_path, kind):
    path = source_file(tmp_path, [{'filename': 'one'}, {'filename': 'two'}])
    with pq.ParquetFile(path) as source, ObservationCounts(source) as counts:
        counts.append(0); counts.append(0); counts.seal(2)
        if kind == 'missing': counts.stream.truncate(8)
        elif kind == 'trailing': counts.stream.seek(0, 2); counts.stream.write(b'x')
        else: counts.stream.seek(0); counts.stream.write(struct.pack('<Q', 1))
        with pytest.raises(ValueError, match='counts'):
            details.publish_details(source, tmp_path / 'details.parquet', observation_counts=counts)


def test_details_use_explicit_counts_without_sidecar_reread_and_keep_canonical_values(tmp_path):
    rows = [dict(filename='José 🏛️\n', body_key='retained-evidence', source_page_title=['Origin', 'Origin'],
                 state_checked_at=['2026-10-14T09:00:00.123999-04:00'], content_labels=['é', 'é', '', '🏛️'],
                 wording=['hidden fragment'], http_status=['200', '404'], response_usable=['false'], source_occurrences=value)
            for value in [None, [], [None], [{'label': ['é', '', 'é']}]]]
    path = source_file(tmp_path, rows)
    with pq.ParquetFile(path) as source, ObservationCounts(source) as counts:
        observations.publish_observations(source, tmp_path, counts=counts)
        (tmp_path / 'observation-rows.bin').unlink()
        (tmp_path / 'observation-index.json').unlink()
        info = details.publish_details(source, tmp_path / 'details.parquet', observation_counts=counts,
            policy=replace(DEFAULT_DECODED_POLICY, batch_arrow_bytes=64))
    assert info['rows'] == 4
    with pq.ParquetFile(tmp_path / 'details.parquet') as written: actual = written.read().to_pylist()
    for i, row in enumerate(actual):
        assert row['filename'] == 'José 🏛️\n'
        assert row['state_checked_at'] == datetime(2026, 10, 14, 13, 0, 0, 123000, tzinfo=timezone.utc)
        assert row['content_labels'] == ['é', 'é', '', '🏛️']
        assert row['body_key'] is None  # conflicting failure evidence never links saved content
        assert row['fact_alternatives'] == [{'field': 'http_status', 'values': ['200', '404']}]
        assert row['source_page_title'] == (['Origin', 'Origin'] if i < 2 else None)
        assert row['filename_readings'] == [] and row['filename_field_count'] == 1


def test_incremental_json_matches_stdlib_numeric_and_unicode_semantics(tmp_path, monkeypatch):
    monkeypatch.setattr(observations, 'BLOCK_BYTES', 7)  # split UTF-8 and numeric tokens
    values = [None, [], {'text': ['é🏛️\n', '', 'é'], 'numbers': [2**100, 1.25, -0.0, 1e-200, 1e200]}]
    writer = observations.Blocks(tmp_path / 'values.bin')
    for value in values: writer.append(value)
    descriptor = writer.close(); actual = []
    for block in descriptor['blocks']: actual.extend(block_items(tmp_path / 'values.bin', block))
    encoded = b''.join(json_chunks(actual, default=decoded_json_default))
    assert encoded == observations.json_bytes(values)
    with pytest.raises(ValueError): observations.json_bytes(float('nan'))
    with pytest.raises(TypeError): observations.json_bytes(Decimal('1.25'))


@pytest.mark.parametrize('fault', ['root', 'count', 'truncated', 'decoded_limit', 'compressed_limit'])
def test_incremental_json_rejects_invalid_blocks(tmp_path, fault):
    value = b'{"item":1}' if fault == 'root' else b'[1]'
    encoded = pa.compress(value, codec='brotli').to_pybytes()
    path = tmp_path / 'values.bin'; path.write_bytes(encoded)
    block = dict(count=1, parts=[[0, len(encoded), len(value)]])
    if fault == 'count': block['count'] = 2
    elif fault == 'truncated': path.write_bytes(encoded[:-1])
    elif fault == 'decoded_limit': block['parts'][0][2] = 2**20 + 1
    elif fault == 'compressed_limit': block['parts'][0][1] = 2**21 + 1
    with pytest.raises(ValueError): list(block_items(path, block))


def test_new_observations_serialize_once_and_dedup_spills(tmp_path):
    rows = [{'source_occurrences': [{'label': ['one']}, {'label': ['one']}, None]}] * 5
    path = source_file(tmp_path, rows); metrics = {}
    with pq.ParquetFile(path) as source: index = observations.publish_observations(source, tmp_path, metrics=metrics)
    assert index['observations']['rows'] == 2
    assert metrics['observation_serializations'] == 15  # once per observed input, never twice for new IDs
    assert metrics['dedup_entries'] == 2 and metrics['dedup_disk_bytes'] > 0
    assert metrics['dedup_sqlite_cache_bytes'] == DEFAULT_DECODED_POLICY.sqlite_cache_kib * 1024
    assert metrics['verification_lookups'] == 15
    assert metrics['decoded_parts'] == sum(len(b['parts']) for key in ('observations', 'references') for b in index[key]['blocks'])


def test_repack_full_arrow_comparison_crosses_adaptive_row_group_boundaries(tmp_path):
    rows = [{'filename': str(i), 'source_occurrences': value} for i, value in enumerate(
        [None, [], [None], [{'label': ['é', '', 'é']}], [{'label': ['🏛️' * 10000]}], [], None])]
    path = source_file(tmp_path, rows); output = tmp_path / 'repacked.parquet'
    info = publisher.repack_and_verify(path, output, publisher.CompressionPolicy(batch_size=5, row_group_size=2),
        decoded_policy=replace(DEFAULT_DECODED_POLICY, batch_arrow_bytes=1024))
    assert info['exact_equal'] and info['rows'] == len(rows)
    with pq.ParquetFile(path) as before, pq.ParquetFile(output) as after:
        assert before.read().equals(after.read(), check_metadata=True)


def test_arrow_only_repack_preserves_large_row_without_estimating_unused_python_values(tmp_path, monkeypatch):
    import filename_budget
    schema = pa.schema([('payload', pa.string()), ('values', pa.list_(pa.string())),
                        ('observations', pa.list_(pa.struct([('label', pa.string())])))],
                       metadata={b'catalog_id': b'stage-budget', b'custom': b'preserve'})
    table = pa.Table.from_pylist([{'payload': 'é' * (5 * 1024**2), 'values': [None, '', 'é', 'é'],
        'observations': [None, {'label': None}, {'label': '🏛️'}, {'label': '🏛️'}]}], schema=schema)
    source, output = tmp_path / 'source.parquet', tmp_path / 'output.parquet'
    pq.write_table(table, source)
    batch = table.to_batches()[0]
    assert 10 * 1024**2 <= batch.nbytes < DEFAULT_DECODED_POLICY.row_arrow_bytes
    assert python_estimate(batch) > DEFAULT_DECODED_POLICY.row_python_estimate
    with open_parquet(source) as reader, pytest.raises(DecodedBudgetExceeded, match='single-row Python/JSON estimate'):
        list(bounded_batches(reader))
    def unused_estimate(batch):
        raise AssertionError('Arrow-only repack or equality attempted a Python estimate')
    monkeypatch.setattr(filename_budget, 'python_estimate', unused_estimate)
    metrics = {}
    result = publisher.repack_and_verify(source, output, metrics=metrics)
    assert result['exact_equal'] and result['rows'] == 1
    # Compare the persisted input schema too: Parquet normalizes list-child
    # names and masked children when the synthetic table is first written.
    with open_parquet(source) as before, open_parquet(output) as after:
        assert before.read().equals(after.read(), check_metadata=True)
    assert metrics['oversized_rows_admitted'] == 3  # write, source equality, output equality
    assert 'max_python_json_estimate' not in metrics
    assert metrics['max_native_batch_rows'] == 1
    assert metrics['max_batch_arrow_bytes'] == batch.nbytes
    assert metrics['max_admitted_buffer_bytes'] >= batch.nbytes


@pytest.mark.parametrize('python_values', [True, False])
def test_true_default_arrow_row_refusal_applies_in_both_conversion_modes(tmp_path, python_values):
    source = tmp_path / 'oversized.parquet'
    pq.write_table(pa.table({'value': ['x' * DEFAULT_DECODED_POLICY.row_arrow_bytes]}), source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    # Four string-offset bytes put this row beyond the unchanged 16 MiB limit.
    with open_parquet(source) as reader, pytest.raises(DecodedBudgetExceeded, match='single-row Arrow bytes'):
        list(bounded_batches(reader, python_values=python_values))
    with pytest.raises(DecodedBudgetExceeded, match='single-row Arrow bytes'):
        publisher.repack_and_verify(source, tmp_path / 'refused.parquet')
    receipt = json.loads((tmp_path / 'preparation-memory-failure.json').read_text())
    assert receipt['source_preserved'] and not receipt['partial_publication_accepted']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('python_values', [True, False])
def test_conversion_mode_controls_only_python_admission_not_stage_names(tmp_path, python_values):
    source = tmp_path / 'modes.parquet'
    table = pa.table({'value': ['é' * 100] * 4})
    pq.write_table(table, source)
    policy = replace(DEFAULT_DECODED_POLICY, batch_arrow_bytes=500, batch_python_estimate=1000,
                     row_python_estimate=2000)
    with open_parquet(source) as reader:
        batches = bounded_batches(reader, policy=policy, python_values=python_values, stage='repack')
        if python_values:
            with pytest.raises(DecodedBudgetExceeded, match='Python/JSON estimate'): list(batches)
        else:
            admitted = list(batches)
            assert all(batch.nbytes <= 500 for batch in admitted)
            assert pa.Table.from_batches(admitted).equals(table)


@pytest.mark.parametrize('invalid', [None, 0, 1, 'false'])
def test_python_conversion_admission_requires_explicit_boolean(invalid):
    with pytest.raises(ValueError, match='python_values must explicitly'):
        list(bounded_batches(None, python_values=invalid))


def test_refused_existing_publication_is_never_overwritten(tmp_path):
    target = tmp_path / 'valid'; target.mkdir(); (target / 'manifest.json').write_text('valid')
    with pytest.raises(ValueError, match='fresh empty'): publisher.publish(tmp_path, target)
    assert (target / 'manifest.json').read_text() == 'valid'
    assert not (target / 'preparation-memory-failure.json').exists()


def test_alias_scan_uses_byte_admission_and_keeps_refusal_scratch(tmp_path):
    from filename_alias_index import AliasIndex
    path = tmp_path / 'aliases.parquet'
    pq.write_table(pa.table({'source_url': ['https://example.test/' + 'x' * 2000]}), path)
    index = AliasIndex(path, policy=replace(DEFAULT_DECODED_POLICY, row_arrow_bytes=1024))
    with pytest.raises(DecodedBudgetExceeded, match='alias index') as caught:
        with index: pass
    assert path.is_file() and (index.folder / 'preparation-memory-failure.json').is_file()
    assert any(str(index.folder) in note for note in caught.value.__notes__)
    import shutil
    shutil.rmtree(index.folder)


def test_logical_block_limit_applies_before_decompression(tmp_path, monkeypatch):
    path = tmp_path / 'values.bin'; path.write_bytes(b'unread')
    monkeypatch.setattr(pa, 'decompress', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('decompressed before admission')))
    with pytest.raises(DecodedBudgetExceeded, match='logical block bytes'):
        list(block_items(path, dict(count=1, parts=[[0, 6, 20]]),
                         policy=replace(DEFAULT_DECODED_POLICY, logical_json_bytes=10)))


def test_python_admission_accounts_for_empty_nested_container_fanout():
    nested = pa.array([[{}] * 10000], type=pa.list_(pa.struct([])))
    batch = pa.record_batch([nested], names=['source_occurrences'])
    class Source:
        def iter_batches(self, **kwargs): return iter([batch])
    assert batch.nbytes < 1024
    with pytest.raises(DecodedBudgetExceeded, match='Python/JSON estimate'):
        list(bounded_batches(Source(), policy=replace(DEFAULT_DECODED_POLICY, row_python_estimate=100000)))


def test_dictionary_page_expansion_is_admitted_after_native_decode(tmp_path):
    path = tmp_path / 'expanded.parquet'
    pq.write_table(pa.table({'value': ['é' * 32768] * 1024}), path, use_dictionary=True)
    metrics = {}
    with pq.ParquetFile(path) as source:
        assert source.metadata.row_group(0).column(0).total_uncompressed_size < 100000
        batches = list(bounded_batches(source, metrics=metrics))
    assert metrics['max_native_batch_arrow_bytes'] > DEFAULT_DECODED_POLICY.batch_arrow_bytes
    assert metrics['max_batch_arrow_bytes'] <= DEFAULT_DECODED_POLICY.batch_arrow_bytes
    assert sum(len(batch) for batch in batches) == 1024
    assert metrics['max_native_batch_rows'] == 128
    converted = []
    with pq.ParquetFile(path) as source, pytest.raises(DecodedBudgetExceeded):
        for batch in bounded_batches(source, policy=replace(DEFAULT_DECODED_POLICY, row_arrow_bytes=1024)):
            converted.append(batch.to_pylist())
    assert converted == []


def test_dictionary_parser_closes_on_canonicalization_failure(tmp_path, monkeypatch):
    path = source_file(tmp_path, [{'source_occurrences': [{'label': ['test']}]}])
    with pq.ParquetFile(path) as source:
        index = observations.publish_observations(source, tmp_path)
        closed = []
        def broken(*args, **kwargs):
            try: yield {'label': float('nan')}
            finally: closed.append(True)
        monkeypatch.setattr(observations, 'block_items', broken)
        with pytest.raises(ValueError): observations.verify_observations(source, tmp_path, index)
        assert closed == [True]


def test_details_coalesce_native_batches_with_exact_order_and_retained_metrics(tmp_path):
    rows = [{'filename': f'row-{i} 🏛️', 'source_occurrences': None} for i in range(400)]
    path = source_file(tmp_path, rows); metrics = {}
    with pq.ParquetFile(path) as source, ObservationCounts(source) as counts:
        for row in rows: counts.append(0)
        counts.seal(len(rows))
        details.publish_details(source, tmp_path / 'details.parquet', observation_counts=counts, metrics=metrics)
    with pq.ParquetFile(tmp_path / 'details.parquet') as written:
        assert written.metadata.num_row_groups == 1
        assert written.read()['filename'].to_pylist() == [row['filename'] for row in rows]
    assert metrics['max_native_batch_rows'] <= 128
    assert metrics['max_detail_staged_buffer_bytes'] >= metrics['max_detail_staged_arrow_bytes']


def test_arrow_staging_checks_limits_before_aggregation_and_keeps_write_error():
    from filename_budget import ArrowStager
    batch = pa.record_batch([['x' * 100] * 4], names=['value'])
    written = []
    class Writer:
        def write_table(self, table, **kwargs): written.append(table)
    staging = ArrowStager(Writer(), batch.schema, row_group_size=6,
                          policy=replace(DEFAULT_DECODED_POLICY, batch_arrow_bytes=600))
    staging.append(batch); staging.append(batch); staging.flush()
    assert [len(table) for table in written] == [4, 4]
    staging.append(pa.record_batch([['x' * 100] * 8], names=['value'])); staging.flush()
    assert all(table.nbytes <= 600 and len(table) <= 6 for table in written)
    strict = ArrowStager(Writer(), batch.schema,
                         policy=replace(DEFAULT_DECODED_POLICY, row_arrow_bytes=100, batch_arrow_bytes=600))
    with pytest.raises(DecodedBudgetExceeded, match='single output-row'):
        strict.append(batch)
    class Broken:
        def write_table(self, *args, **kwargs): raise OSError('injected staged write')
    staging = ArrowStager(Broken(), batch.schema)
    staging.append(batch)
    with pytest.raises(OSError, match='injected staged write'): staging.flush()


def test_borrowed_reader_survives_repack_failure_and_owned_output_closes(tmp_path, monkeypatch):
    path = source_file(tmp_path, [{'filename': 'one'}, {'filename': 'two'}])
    original_open, original_batches = publisher.open_parquet, publisher.bounded_batches
    acquired = []
    def opening(candidate):
        result = original_open(candidate); acquired.append(result); return result
    monkeypatch.setattr(publisher, 'open_parquet', opening)
    with open_parquet(path) as source:
        def batches(candidate, **kwargs):
            if candidate is not source: raise ValueError('injected output readback')
            return original_batches(candidate, **kwargs)
        monkeypatch.setattr(publisher, 'bounded_batches', batches)
        with pytest.raises(ValueError, match='injected output readback'):
            publisher.repack_and_verify(source, tmp_path / 'copy.parquet')
        assert not source.closed and source.read().num_rows == 2
    assert acquired and all(reader.closed for reader in acquired)


def test_publication_reuses_its_catalog_readers_and_preparation_options(tmp_path, monkeypatch):
    import subprocess, sys
    fixture = Path(__file__).resolve().parents[1] / 'apps/site/scripts/filename-test-fixture.py'
    root = tmp_path / 'fixture'
    subprocess.run([sys.executable, str(fixture), str(root)], check=True, capture_output=True)
    manifest = json.loads((root / 'indexes/catalog.json').read_text())
    source_paths = {root / item['key'] for item in manifest['files'].values()}
    original_file, original_catalog, original_repack = pq.ParquetFile, publisher.viewer.Catalog, publisher.repack_and_verify
    opens, catalog, repacks = [], [], []
    def opening(path, *args, **kwargs):
        if path in source_paths: opens.append((path, kwargs))
        return original_file(path, *args, **kwargs)
    def catalog_open(*args, **kwargs):
        value = original_catalog(*args, **kwargs); catalog.append(value); return value
    def repack(source, destination, *args, **kwargs):
        assert destination.name == 'filenames.parquet' and source is catalog[0].file
        repacks.append(destination.name)
        return original_repack(source, destination, *args, **kwargs)
    monkeypatch.setattr(pq, 'ParquetFile', opening)
    monkeypatch.setattr(publisher.viewer, 'Catalog', catalog_open)
    monkeypatch.setattr(publisher, 'repack_and_verify', repack)
    publisher.publish(root, tmp_path / 'public', review_identities=None)
    assert repacks == ['filenames.parquet']
    # One independent manifest check plus one owned Catalog open per input.
    assert all(sum(path == candidate for candidate, _ in opens) == 2 for path in source_paths)
    preparation = [options for _, options in opens if options]
    assert preparation == [{'pre_buffer': False, 'buffer_size': 65536}] * 2
    assert catalog[0].file.closed and catalog[0].document_file.closed
