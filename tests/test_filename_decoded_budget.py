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
                             json_chunks)
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


def test_physical_admission_precedes_any_decode_including_later_groups(tmp_path):
    path = source_file(tmp_path, [{'filename': 'x'}] * 3 + [{'filename': 'x' * 20000}])
    with pq.ParquetFile(path) as source:
        class NoDecode:
            metadata = source.metadata
            def iter_batches(self, **kwargs): raise AssertionError('decoded before preflight completed')
        with pytest.raises(DecodedBudgetExceeded, match='row-group 1'):
            list(bounded_batches(NoDecode(), columns=['filename'], policy=replace(DEFAULT_DECODED_POLICY, physical_group_bytes=1024)))


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
