"""Component chunks stream beyond one-row limits without relaxing row admission."""
from contextlib import contextmanager
from dataclasses import replace
import base64
import json
import sqlite3
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.catalog_cache import LocalStore
from viewer_publication.filename_budget import DEFAULT_DECODED_POLICY, DecodedBudgetExceeded
from viewer_publication.filename_native import NativeComponents, ViewerAssets


class Native:
    def __init__(self, table):
        self.table, self.reads = table, 0
        self.tables = {"selected": table}

    @contextmanager
    def source_batches(self, pin, *, schema=None):
        self.reads += 1
        table = self.tables[pin["dataset"]["dataset"]]
        assert table.schema.equals(schema, check_metadata=True)
        with table.to_reader(max_chunksize=64) as reader:
            yield reader


    def run_table(self, table, **request):
        self.tables[request['dataset']] = table
        return dict(id='initial', verified=True, dataset=dict(dataset=request['dataset'], computed={}, related=None,
                    evidence=None, groups=dict(source=dict(rows=len(table)))))


@contextmanager
def chunk(tmp_path, label, payloads, *, policy=DEFAULT_DECODED_POLICY, observations=False):
    rows = [dict(source_id=f'source-{index}', document_id=f'doc-{index}',
                 filename=f'{index}.pdf', source_url=value if label == 'filenames' else 'https://example.org/',
                 payload=value if label == 'documents' else None)
            for index, value in enumerate(payloads)]
    schema = pa.schema([(name, pa.string()) for name in rows[0]], metadata={b'catalog_id': b'chunk-budget'})
    if observations:
        schema = schema.append(pa.field('source_occurrences', pa.list_(pa.struct([('label', pa.list_(pa.string()))]))))
        for index, row in enumerate(rows):
            row['source_occurrences'] = [None, [], [None], [{'label': ['é', str(index), None]}]][index % 4]
    expected = pa.Table.from_pylist(rows, schema=schema)
    physical = expected.append_column(pa.field('_catalog_order', pa.int64(), nullable=False),
                                      pa.array(range(len(rows)), type=pa.int64()))
    native = Native(physical)
    snapshot = SimpleNamespace(native=native, store=LocalStore(tmp_path / 'store'))
    assets, metrics = ViewerAssets(tmp_path / 'assets'), {}
    with sqlite3.connect(':memory:') as db:
        current = NativeComponents(snapshot, assets, None, db, policy=policy, metrics=metrics)
        name = 'bounded-chunk'
        pin = dict(verified=True, dataset=dict(dataset='selected', computed={}, related=None, evidence=None,
                   groups=dict(source=dict(rows=len(rows)))))
        if observations:
            from congress_api.retention.catalog_rows import CatalogRows
            pin = CatalogRows(native=native, store=snapshot.store).write(physical, dataset='typed-chunk',
                operation='typed-chunk', definition='chunk-budget', max_rows=10000, max_bytes=96 * 1024**2,
                owner_column='document_id')
        text = base64.b64encode(schema.serialize()).decode()
        db.executemany('INSERT INTO components(id) VALUES (?)', ((row['document_id'],) for row in rows))
        db.executemany('INSERT INTO stats VALUES (?,0,0,0,0)', ((row['document_id'],) for row in rows))
        db.executemany('INSERT INTO views VALUES (?,?,1)', ((name, row['document_id']) for row in rows))
        db.commit()
        yield current, (name, label, json.dumps(pin), text), expected


@pytest.mark.parametrize('label', ['documents', 'filenames'])
def test_multibatch_chunk_exceeds_row_budget_and_preserves_every_value(tmp_path, label):
    payloads = ['é' * 12288 + str(index) for index in range(1024)]
    policy = replace(DEFAULT_DECODED_POLICY, batch_arrow_bytes=128 * 1024,
                     writer_buffer_bytes=512 * 1024)
    with chunk(tmp_path, label, payloads, policy=policy) as (current, args, expected):
        assert expected.nbytes > policy.row_arrow_bytes
        assert len(current.snapshot.native.table.to_batches(max_chunksize=64)) > 1
        with current.db:
            current._prepare_chunk(*args)
        assert current.snapshot.native.reads == 1
        assert current.metrics['max_batch_arrow_bytes'] <= policy.batch_arrow_bytes
        if label == 'documents':
            raw, = current.db.execute('SELECT reference FROM chunk_assets').fetchone()
            reference = json.loads(raw)['document_file']
            with pq.ParquetFile(current.assets.root / reference['path']) as written:
                actual = written.read()
                assert written.metadata.num_row_groups > 1
            assert reference['rows'] == len(expected)
            assert actual.equals(expected, check_metadata=True)
            records = {identity: json.loads(raw) for identity, raw in
                       current.db.execute('SELECT id,record FROM components')}
            assert all(records[row['document_id']] == {key: value for key, value in row.items() if key != 'payload'}
                       for row in expected.to_pylist())
            assert current.metrics['max_native_component_documents_pending_buffer_bytes'] <= policy.writer_buffer_bytes
            assert current.metrics['max_native_component_documents_staged_arrow_bytes'] < expected.nbytes
        else:
            assert list(current.db.execute('SELECT id,source_order,source_id FROM member_ids ORDER BY source_order')) == [
                (row['document_id'], index, row['source_id']) for index, row in enumerate(expected.to_pylist())]
            assert current.db.execute('SELECT sum(n),sum(saved),sum(api),sum(video) FROM stats').fetchone() == (1024,0,0,0)
            assert current.db.execute('SELECT count(*) FROM chunk_assets').fetchone()[0] == 0


@pytest.mark.parametrize('label', ['documents', 'filenames'])
def test_oversized_single_row_refuses_without_accepting_partial_chunk(tmp_path, label):
    with chunk(tmp_path, label, ['small', 'x' * (DEFAULT_DECODED_POLICY.row_arrow_bytes + 1)]) as (current, args, _):
        with pytest.raises(DecodedBudgetExceeded, match='single-row Arrow bytes'), current.db:
            current._prepare_chunk(*args)
        assert not current.assets.identities
        assert current.db.execute('SELECT count(*) FROM chunk_assets').fetchone()[0] == 0
        assert current.db.execute('SELECT count(*) FROM member_ids').fetchone()[0] == 0
        assert current.db.execute('SELECT count(record) FROM components').fetchone()[0] == 0


def test_large_typed_chunk_keeps_occurrences_in_exact_document_order(tmp_path, monkeypatch):
    from viewer_publication import filename_native
    original = filename_native.typed_observations
    retained = []
    def observed(schema, identities, occurrences):
        retained.append(identities)
        # A retained ID slice must never own a complete wide input frame.
        for chunk in identities.chunks:
            for buffer in chunk.buffers():
                while buffer is not None and buffer.parent is not None:
                    buffer = buffer.parent
                    assert buffer.size <= chunk.get_total_buffer_size()
        return original(schema, identities, occurrences)
    monkeypatch.setattr(filename_native, 'typed_observations', observed)
    with chunk(tmp_path, 'documents', ['x' * 65536 + str(i) for i in range(300)],
               observations=True) as (current, args, expected):
        assert expected.nbytes > DEFAULT_DECODED_POLICY.row_arrow_bytes
        with current.db:
            current._prepare_chunk(*args)
        raw, = current.db.execute('SELECT reference FROM chunk_assets').fetchone()
        reference = json.loads(raw)
        with pq.ParquetFile(current.assets.root / reference['document_file']['path']) as file:
            assert file.read().equals(expected.drop(['source_occurrences']), check_metadata=True)
        assert reference['document_observations']['rows'] == len(expected)
        assert len(retained) == 1 and retained[0].num_chunks > 1
        assert retained[0].to_pylist() == expected['document_id'].to_pylist()
        assert retained[0].get_total_buffer_size() < 8192
        from viewer_publication.filename_observations import block_items
        files = reference['document_observations']['files']
        assert 'occurrences' not in files
        index = json.loads((current.assets.root / files['observation_index']['path']).read_bytes())
        dictionary = [value for block in index['observations']['blocks'] for value in
                      block_items(current.assets.root / files['observations']['path'], block)]
        refs = [value for block in index['references']['blocks'] for value in
                block_items(current.assets.root / files['observation_rows']['path'], block)]
        actual = [None if row is None else [None if dictionary[i] is None else
                  {field:dictionary[i].get(field) for field in index['fields']} for i in row] for row in refs]
        assert actual == expected['source_occurrences'].to_pylist()
