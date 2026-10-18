"""The publication verifier must compare every nested value and reference."""
import copy
import importlib.util
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

spec = importlib.util.spec_from_file_location('observation_publication',
    Path(__file__).resolve().parents[1] / 'apps/site/scripts/filename_observations.py')
observations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observations)


def publication(tmp_path, monkeypatch):
    monkeypatch.setattr(observations, 'BLOCK_BYTES', 128)
    values = [None, [], [None], [{'label': None, 'links': []}],
              [{'label': ['José 🏛️' * 100], 'links': ['https://committee.test/hearing']}],
              [{'label': ['one']}, {'label': ['two']}, {'label': ['one']}]]
    schema = pa.schema([('source_occurrences', pa.list_(pa.struct([
        ('label', pa.list_(pa.string())), ('links', pa.list_(pa.string()))])))])
    path = tmp_path / 'source.parquet'
    pq.write_table(pa.Table.from_pylist([{'source_occurrences': row} for row in values], schema=schema), path)
    source = pq.ParquetFile(path)
    index = observations.publish_observations(source, tmp_path)
    return source, index


def test_disk_verifier_preserves_null_empty_unicode_duplicates_and_multipart(tmp_path, monkeypatch):
    source, index = publication(tmp_path, monkeypatch)
    assert any(len(block['parts']) > 1 for block in index['observations']['blocks'])
    observations.verify_observations(source, tmp_path, index)


@pytest.mark.parametrize('fault', ['value', 'reorder', 'missing', 'null', 'trailing', 'schema', 'offset', 'reference_type'])
def test_disk_verifier_rejects_changed_values_or_references(tmp_path, monkeypatch, fault):
    source, index = publication(tmp_path, monkeypatch)
    index = copy.deepcopy(index)
    if fault == 'offset':
        index['references']['blocks'][0]['start'] = 1
    elif fault == 'schema':
        index['fields'] = ['label']
    elif fault == 'value':
        writer = observations.Blocks(tmp_path / 'observations.bin')
        for value in [None, {'links': []}, {'label': ['corrupt']}, {'label': ['one']}, {'label': ['two']}]:
            writer.append(value)
        index['observations'] = writer.close()
    else:
        writer = observations.Blocks(tmp_path / 'observation-rows.bin')
        rows = [None, [], [0], [1], [2], [3, 4, 3]]
        if fault == 'reorder': rows[-1] = [4, 3, 3]
        if fault == 'missing': rows[-1] = [3, 99, 3]
        if fault == 'reference_type': rows[-1] = [3, '4', 3]
        if fault == 'null': rows[1] = None
        if fault == 'trailing': rows.append([])
        for row in rows:
            writer.append(row)
        index['references'] = writer.close()
    with pytest.raises(ValueError):
        observations.verify_observations(source, tmp_path, index)


def test_each_dictionary_part_is_decoded_once_despite_distant_reuse(tmp_path, monkeypatch):
    monkeypatch.setattr(observations, 'BLOCK_BYTES', 64)
    schema = pa.schema([('source_occurrences', pa.list_(pa.struct([('label', pa.list_(pa.string()))])))])
    rows = [{'source_occurrences': [{'label': [str(i) * 50]}]} for i in range(20)] * 5
    path = tmp_path / 'source.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    source = pq.ParquetFile(path)
    index = observations.publish_observations(source, tmp_path)
    decompress = observations.pa.decompress
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return decompress(*args, **kwargs)

    monkeypatch.setattr(observations.pa, 'decompress', counted)
    observations.verify_observations(source, tmp_path, index)
    assert len(calls) == sum(len(block['parts']) for name in ('observations', 'references')
                             for block in index[name]['blocks'])


@pytest.mark.parametrize('failure', ['second_open', 'serialize', 'compress', 'write', 'verify'])
def test_all_observation_writers_close_and_abort_never_flushes_pending_rows(tmp_path, monkeypatch, failure):
    schema = pa.schema([('source_occurrences', pa.list_(pa.struct([('label', pa.list_(pa.string()))])))])
    source = pa.Table.from_pylist([{'source_occurrences': [{'label': ['complete value']}]}], schema=schema)
    class Source:
        schema_arrow = schema
        def iter_batches(self, **kwargs): return iter(source.to_batches())
    opened, flushed = [], []
    Original = observations.Blocks
    class Tracked(Original):
        def __init__(self, path, *args, **kwargs):
            if failure == 'second_open' and path.name == 'observation-rows.bin': raise OSError('injected second_open')
            super().__init__(path, *args, **kwargs); opened.append(self)
            if failure == 'write':
                original = self.stream
                class Broken:
                    @property
                    def closed(self): return original.closed
                    def tell(self): return original.tell()
                    def write(self, value): raise OSError('injected write')
                    def close(self): original.close()
                self.stream = Broken()
        def flush(self):
            flushed.append(self.path.name)
            return super().flush()
    monkeypatch.setattr(observations, 'Blocks', Tracked)
    if failure == 'serialize': monkeypatch.setattr(observations, 'json_chunks', lambda *a, **kw: (_ for _ in ()).throw(ValueError('injected serialize')))
    elif failure == 'compress': monkeypatch.setattr(observations.pa, 'compress', lambda *a, **kw: (_ for _ in ()).throw(ValueError('injected compress')))
    elif failure == 'verify': monkeypatch.setattr(observations, 'verify_observations', lambda *a, **kw: (_ for _ in ()).throw(ValueError('injected verify')))
    with pytest.raises((OSError, ValueError), match='injected'):
        observations.publish_observations(Source(), tmp_path)
    assert opened and all(writer.stream.closed for writer in opened)
    assert not (tmp_path / 'observation-index.json').exists()
    if failure in ('second_open', 'serialize'): assert flushed == []


def test_resource_cleanup_keeps_primary_exception_and_records_close_error():
    from filename_resources import owned_resources
    class Reader:
        def __enter__(self): return self
        def __exit__(self, *args): raise OSError('injected close failure')
    with pytest.raises(ValueError, match='primary value error') as caught:
        with owned_resources() as owned:
            owned.enter_context(Reader())
            raise ValueError('primary value error')
    assert any('injected close failure' in note for note in caught.value.__notes__)


def test_default_budget_accepts_many_small_units_without_converting_the_outer_list(tmp_path):
    from filename_budget import DEFAULT_DECODED_POLICY, python_estimate
    from filename_json_stream import ObservationCounts
    fields = [('label', pa.list_(pa.string()))] + [(f'context_{i}', pa.list_(pa.string())) for i in range(12)]
    kind = pa.list_(pa.struct(fields))
    # Many ordinary observations can exceed the whole-list Python estimate even
    # though each converted struct and the retained reference list are small.
    repeated = {'label': ['José 🏛️', '', 'José 🏛️']}
    values = [repeated, None] * 30000
    table = pa.Table.from_arrays([pa.array([values], type=kind)], names=['source_occurrences'])
    batch = table.to_batches()[0]
    assert batch.nbytes < DEFAULT_DECODED_POLICY.row_arrow_bytes
    assert python_estimate(batch) > DEFAULT_DECODED_POLICY.row_python_estimate
    path = tmp_path / 'source.parquet'
    pq.write_table(table, path)
    with pq.ParquetFile(path) as source, ObservationCounts(source) as counts:
        metrics = {}
        index = observations.publish_observations(source, tmp_path, counts=counts, metrics=metrics)
        assert list(counts.values(source)) == [60000]
        observations.verify_observations(source, tmp_path, index)
    assert index['observations']['rows'] == 2
    assert index['references']['rows'] == 1
    assert metrics['observation_serializations'] == 60000
    assert metrics['verification_lookups'] == 60000
    assert metrics['max_observation_python_estimate'] < DEFAULT_DECODED_POLICY.row_python_estimate
    assert metrics['max_reference_list_python_estimate'] == 64 + 48 * 60000


@pytest.mark.parametrize('stage', ['observations', 'observation verification'])
def test_single_observation_refuses_before_python_conversion(stage):
    from dataclasses import replace
    from filename_budget import DEFAULT_DECODED_POLICY, DecodedBudgetExceeded
    values = pa.array([{'label': ['é🏛️' * 1000]}], type=pa.struct([('label', pa.list_(pa.string()))]))
    class Guarded:
        def slice(self, *args): return values.slice(*args)
        def __getitem__(self, index): raise AssertionError('conversion accessed before admission')
    with pytest.raises(DecodedBudgetExceeded, match='single-observation Python/JSON estimate'):
        observations.observation_value(Guarded(), 0,
            policy=replace(DEFAULT_DECODED_POLICY, row_python_estimate=1024), metrics={}, stage=stage)


def test_reference_list_refuses_before_allocating_or_converting_observations(tmp_path, monkeypatch):
    from dataclasses import replace
    from filename_budget import DEFAULT_DECODED_POLICY, DecodedBudgetExceeded
    table = pa.table({'source_occurrences': pa.array([[{}] * 30], type=pa.list_(pa.struct([('label', pa.string())])))})
    class Source:
        schema_arrow = table.schema
        def iter_batches(self, **kwargs): return iter(table.to_batches())
    def unexpected(*args, **kwargs): raise AssertionError('no reference allocation or observation conversion expected')
    monkeypatch.setattr(observations, 'observation_value', unexpected)
    with pytest.raises(DecodedBudgetExceeded, match='reference-list Python estimate'):
        observations.publish_observations(Source(), tmp_path,
            policy=replace(DEFAULT_DECODED_POLICY, row_python_estimate=1024))
    assert not (tmp_path / 'observation-index.json').exists()


def test_conversion_units_preserve_exact_dictionary_and_reference_encoding(tmp_path, monkeypatch):
    source, index = publication(tmp_path, monkeypatch)
    expected = tmp_path / 'expected'; expected.mkdir()
    dictionary = observations.Blocks(expected / 'observations.bin')
    for value in [None, {'links': []}, {'label': ['José 🏛️' * 100], 'links': ['https://committee.test/hearing']},
                  {'label': ['one']}, {'label': ['two']}]:
        dictionary.append(value)
    dictionary_index = dictionary.close()
    references = observations.Blocks(expected / 'observation-rows.bin', row_limit=1024)
    for row in [None, [], [0], [1], [2], [3, 4, 3]]: references.append(row)
    reference_index = references.close()
    assert index['observations'] == dictionary_index
    assert index['references'] == reference_index
    for filename in ['observations.bin', 'observation-rows.bin']:
        assert (tmp_path / filename).read_bytes() == (expected / filename).read_bytes()
    source.close()


def test_arrow_list_slices_keep_offsets_nulls_timestamps_types_and_order(tmp_path):
    kind = pa.list_(pa.struct([('label', pa.list_(pa.string())), ('at', pa.string()),
                               ('number', pa.int64()), ('usable', pa.bool_())]))
    first = {'label': ['β', '', 'β'], 'at': '2026-10-14T09:00:00.123999-04:00', 'number': 2**53 + 1, 'usable': False}
    second = {'label': [], 'at': '', 'number': -1, 'usable': True}
    values = [[{'label': ['outside-before']}], None, [], [None, first, second, first], [{'label': ['outside-after']}]]
    table = pa.Table.from_arrays([pa.array(values, type=kind)], names=['source_occurrences']).slice(1, 3)
    class Source:
        schema_arrow = table.schema
        def iter_batches(self, **kwargs): return iter(table.to_batches(max_chunksize=2))
    source = Source()
    index = observations.publish_observations(source, tmp_path)
    def decoded(name, descriptor):
        return [value for block in descriptor['blocks']
                for value in observations.block_items(tmp_path / name, block)]
    assert decoded('observations.bin', index['observations']) == [None, first, second]
    assert decoded('observation-rows.bin', index['references']) == [None, [], [0, 1, 2, 1]]
    observations.verify_observations(source, tmp_path, index)
