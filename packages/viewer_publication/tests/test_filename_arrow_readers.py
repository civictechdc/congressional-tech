"""Retained Arrow leaves share physical-reader admission and detail semantics."""
from collections import Counter
from dataclasses import replace
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY, DecodedBudgetExceeded, bounded_batches
from viewer_publication.filename_details import publish_details
from viewer_publication.filename_json_stream import ObservationCounts


def counts_for(source, values):
    counts = ObservationCounts(source)
    for value in values:
        counts.append(value)
    counts.seal(len(values))
    return counts


def detail_table():
    schema = pa.schema([
        ('source_id', pa.string()), ('filename', pa.string()), ('body_key', pa.string()),
        ('source_url', pa.string()), ('record_role', pa.list_(pa.string())),
        ('source_page_title', pa.list_(pa.string())), ('source_link_label', pa.list_(pa.string())),
        ('congress', pa.list_(pa.string())), ('format', pa.list_(pa.string())),
        ('document_kind', pa.list_(pa.string())), ('document_family', pa.list_(pa.string())),
        ('http_status', pa.list_(pa.string())), ('response_usable', pa.list_(pa.string())),
        ('response_body_complete', pa.list_(pa.string())), ('state_checked_at', pa.list_(pa.string())),
        ('normalized_leaf', pa.list_(pa.string())), ('content_labels', pa.list_(pa.string())),
    ], metadata={b'catalog_id': b'arrow-reader-fixture'})
    rows = [dict(source_id=f'source-{i}', filename=f'{i}-José 🏛️.pdf',
        body_key='bodies/sha256/ab/' + 'ab' * 32 + '.gz', source_url=f'https://committee.test/{i}',
        record_role=['document'], source_page_title=['Hearing'], source_link_label=['Witness'],
        congress=['118'], format=['PDF'], document_kind=['statement'], document_family=['hearing'],
        http_status=['200'] if i % 2 else ['200', '404'], response_usable=['true'],
        response_body_complete=['true'], state_checked_at=['2026-10-14T09:00:00-04:00'],
        normalized_leaf=[] if i % 2 else ['one', '', 'one'], content_labels=None if i % 2 else [])
        for i in range(9)]
    table = pa.Table.from_pylist(rows, schema=schema)
    return pa.concat_tables([table.slice(0, 4), table.slice(4)]).slice(1, 7)


@pytest.mark.parametrize('empty', [False, True])
def test_arrow_and_parquet_detail_readers_emit_identical_physical_output(tmp_path, empty):
    table = detail_table()
    if empty:
        table = table.slice(0, 0)
    core = tmp_path / 'filenames.parquet'
    pq.write_table(table, core, row_group_size=2)
    policy = replace(DEFAULT_DECODED_POLICY, native_batch_rows=3)
    values = [0, 1, 0, 2, 1, 0, 1][:len(table)]
    with pq.ParquetFile(core) as physical:
        # Preserve the already-written export's logical schema, including list names.
        retained = table.cast(physical.schema_arrow)
        with counts_for(physical, values) as counts:
            expected = publish_details(physical, tmp_path / 'physical-details.parquet',
                observation_counts=counts, policy=policy)
    with counts_for(retained, values) as counts:
        actual = publish_details(retained, tmp_path / 'arrow-details.parquet',
            observation_counts=counts, policy=policy)
    assert actual == expected
    assert (tmp_path / 'arrow-details.parquet').read_bytes() == (tmp_path / 'physical-details.parquet').read_bytes()
    rows = pq.read_table(tmp_path / 'arrow-details.parquet').to_pylist()
    assert [row['source_id'] for row in rows] == table['source_id'].to_pylist()
    if rows:
        assert rows[0]['source_link_label'] == ['Witness'] and rows[1]['source_link_label'] is None
        assert rows[1]['http_status'] is None and rows[1]['fact_alternatives']


def test_arrow_batch_admission_projects_sliced_chunked_values_and_refuses_large_rows():
    table = detail_table()
    policy = replace(DEFAULT_DECODED_POLICY, native_batch_rows=3, batch_arrow_bytes=64,
                     batch_python_estimate=2048)
    batches = list(bounded_batches(table, columns=['filename'], policy=policy))
    assert [row['filename'] for batch in batches for row in batch.to_pylist()] == table['filename'].to_pylist()
    assert all(batch.schema.names == ['filename'] and (len(batch) == 1 or batch.nbytes <= 64) for batch in batches)
    oversized = pa.table({'filename': ['é' * 1000]})
    with pytest.raises(DecodedBudgetExceeded, match='single-row Arrow bytes'):
        list(bounded_batches(oversized, policy=replace(policy, row_arrow_bytes=100)))
    with pytest.raises(DecodedBudgetExceeded, match='single-row Python/JSON estimate'):
        list(bounded_batches(oversized, policy=replace(policy, row_python_estimate=100)))
    assert sum(len(batch) for batch in bounded_batches(table, columns=[])) == len(table)


def test_arrow_observation_counts_keep_exact_source_ownership(tmp_path):
    table = detail_table()
    with counts_for(table, [0] * len(table)) as counts:
        with pytest.raises(ValueError, match='do not cover this source'):
            publish_details(table.slice(0), tmp_path / 'other.parquet', observation_counts=counts)


def test_native_source_details_and_facets_do_not_decode_generated_core_parquet(tmp_path, monkeypatch):
    sys.path[:0] = [str(Path(__file__).resolve().parents[2] / 'congress_api/tests')]
    from congress_api.retention.catalog_cache import LocalStore
    from congress_api.retention.catalog_publication import read_catalog
    from test_catalog_coalesced_batches import Native
    from test_native_catalog_selection import seed
    from viewer_publication.filename_native import NativeSourceAssets, ViewerAssets
    store, native = LocalStore(tmp_path / 'store'), Native()
    seed(tmp_path, store, native)
    selected = read_catalog(store, native=native)
    scans = Counter()
    original = pq.ParquetFile
    class Traced(original):
        def __init__(self, source, *args, **kwargs):
            self.fixture_path = Path(source) if isinstance(source, (str, Path)) else None
            super().__init__(source, *args, **kwargs)
        def iter_batches(self, *args, **kwargs):
            if self.fixture_path and self.fixture_path.name in ('filenames.parquet', 'details.parquet'):
                scans[self.fixture_path.name] += 1
            yield from super().iter_batches(*args, **kwargs)
    monkeypatch.setattr(pq, 'ParquetFile', Traced)
    assets = ViewerAssets(tmp_path / 'assets')
    root = NativeSourceAssets(selected, assets, policy=DEFAULT_DECODED_POLICY, metrics={}).render(
        selected.selection['dependency']['source_root'])
    assert root['stats']['rows'] == 4
    assert scans == {'details.parquet': 1}, dict(scans)


@pytest.mark.parametrize('fault', ['missing', 'trailing', 'changed'])
def test_arrow_details_reject_corrupted_owned_counts(tmp_path, fault):
    import struct
    table = detail_table()
    with counts_for(table, [0] * len(table)) as counts:
        if fault == 'missing': counts.stream.truncate(8)
        elif fault == 'trailing': counts.stream.seek(0, 2); counts.stream.write(b'x')
        else: counts.stream.seek(0); counts.stream.write(struct.pack('<Q', 1))
        with pytest.raises(ValueError, match='counts'):
            publish_details(table, tmp_path / 'details.parquet', observation_counts=counts)


def test_arrow_details_still_verify_derived_output_values(tmp_path, monkeypatch):
    from viewer_publication import filename_details
    table = detail_table()
    original = filename_details.open_parquet
    def corrupted(path):
        data = pq.read_table(path)
        rows = data.to_pylist()
        rows[0]['filename'] = 'changed after write'
        pq.write_table(pa.Table.from_pylist(rows, schema=data.schema), path)
        return original(path)
    monkeypatch.setattr(filename_details, 'open_parquet', corrupted)
    with counts_for(table, [0] * len(table)) as counts:
        with pytest.raises(ValueError, match='Detail values changed'):
            publish_details(table, tmp_path / 'details.parquet', observation_counts=counts)
