"""The application calls the maintained source-only lifecycle with exact requests."""
from hashlib import sha256
import os
from pathlib import Path
import shutil

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from congress_api.retention.docspec import DocSpecFailure
from native_test_helpers import native_test_client


@pytest.fixture
def native(tmp_path):
    binary = os.environ.get('DOCSPEC_BINARY') or shutil.which('docspec')
    if not binary:
        pytest.skip('Set DOCSPEC_BINARY to the qualified maintained CLI')
    return native_test_client(binary, tmp_path / 'workspace')


def inventory(root):
    return {str(p.relative_to(root)): sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def test_exact_source_pins_nested_values_and_completed_retry(native, tmp_path):
    schema = pa.schema([
        pa.field('record_key', pa.string(), nullable=False, metadata={b'application_field': b'key'}),
        ('values', pa.list_(pa.struct([('name', pa.string()), ('items', pa.list_(pa.string()))]))),
    ], metadata={b'application_identity': b'unchanged'})
    rows = [dict(record_key='a', values=None), dict(record_key='b', values=[]),
            dict(record_key='c', values=[dict(name='', items=[]), dict(name='', items=[])])]
    path = tmp_path / 'source.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), path)
    build = dict(dataset='adapter-source', operation='initial', definition='adapter-v1',
                 sql='SELECT * FROM input', input=str(path), expected_digest=native.hash_input(path)['digest'])
    first = native.run(build)
    with native.source_batches(first) as reader:
        assert reader.schema.equals(schema, check_metadata=False)
        assert reader.schema.metadata is None
        assert reader.read_all().select(schema.names).to_pylist() == rows
    assert native.latest('adapter-source') == first
    assert native.release('adapter-source', 'initial') == first
    replacement = tmp_path / 'replacement.parquet'
    corrected = dict(record_key='b', values=[dict(name='corrected', items=None)])
    pq.write_table(pa.Table.from_pylist([corrected], schema=schema), replacement)
    change = dict(dataset='adapter-source', operation='changed', definition='adapter-v1',
                  base=first['id'], keys=['record_key'], replacements=dict(
                      path=str(replacement), digest=native.hash_input(replacement)['digest']))
    second = native.update(change)
    with native.source_batches(second) as reader:
        assert reader.schema.equals(schema, check_metadata=False)
        actual = reader.read_all()
        assert set(actual.column_names) == set(schema.names)
        assert {r['record_key']: r for r in actual.to_pylist()} == {
            r['record_key']: r for r in [rows[0], corrected, rows[2]]}
    with native.source_batches(first) as reader:
        assert reader.read_all().to_pylist() == rows
    path.rename(path.with_suffix('.unavailable'))
    replacement.rename(replacement.with_suffix('.unavailable'))
    before = inventory(native.workspace)
    assert native.plan_update(change)['completed'] is True
    assert native.update(change) == second
    assert inventory(native.workspace) == before
    with pytest.raises(DocSpecFailure, match='stale_base'):
        native.update({**change, 'operation': 'stale'})


def test_native_refusals_preserve_error_and_cleanup_request_files(native, tmp_path):
    with pytest.raises(DocSpecFailure):
        native.run(dict(dataset='missing-source', operation='initial', definition='v1',
                        sql='SELECT * FROM input', input=str(tmp_path / 'absent.parquet'),
                        expected_digest='0' * 64))
    assert not list(native.workspace.glob('request-*'))


def test_raw_values_roundtrip_native_source_without_losing_occurrences(native, tmp_path):
    from congress_api.retention.raw_archive import CAPTURE_SCHEMA
    from congress_api.retention.raw_values import capture_table, ordered_captures

    original = pa.Table.from_pylist([
        dict(body_key='bodies/one.gz', receipt_key='receipts/one.gz', receipt_line=1,
             http_status=200, resolution='saved', original_path=None),
        dict(body_key=None, receipt_key='receipts/one.gz', receipt_line=2,
             http_status=429, resolution='retry_later', original_path=''),
        dict(body_key='bodies/one.gz', receipt_key='receipts/two.gz', receipt_line=1,
             http_status=200, resolution='saved', original_path=None),
    ], schema=CAPTURE_SCHEMA)
    path = tmp_path / 'raw.parquet'
    pq.write_table(capture_table(original, first_order=37), path)
    pin = native.run(dict(dataset='raw-value-proof', operation='initial', definition='raw-v1',
                          sql='SELECT * FROM input', input=str(path),
                          expected_digest=native.hash_input(path)['digest']))
    with native.source_batches(pin) as reader:
        restored = ordered_captures(reader.read_all())
    assert restored.equals(original)


def test_source_table_candidate_replays_with_a_fresh_input_locator(native):
    table = pa.table({'key': ['one', 'two'], 'values': [None, ['same', 'same']]})
    first = native.run_table(table, dataset='table-candidate', operation='initial', definition='table-v1')
    before = inventory(native.workspace)
    again = native.run_table(table, dataset='table-candidate', operation='initial', definition='table-v1')
    assert again == first
    assert inventory(native.workspace) == before
    with native.source_batches(first) as reader:
        assert reader.read_all().to_pylist() == table.to_pylist()
