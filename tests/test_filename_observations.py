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
