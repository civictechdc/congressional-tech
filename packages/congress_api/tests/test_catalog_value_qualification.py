"""Full qualification compares actual old/new values, including canonical IDs."""
from contextlib import ExitStack
from copy import deepcopy
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from congress_api.retention.catalog_qualification import qualify_complete_values
from testing_fakes import MemoryStore

SCHEMA = pa.schema([('document_id', pa.string()), ('source_id', pa.string()),
                    ('values', pa.list_(pa.string()))])
ROWS = [dict(document_id='a', source_id='canonical-a', values=['same', 'same', None]),
        dict(document_id='b', source_id='canonical-b', values=[])]


def files(tmp_path, rows, schema=SCHEMA):
    pq.write_table(pa.Table.from_pylist(ROWS, schema=SCHEMA), tmp_path / 'old.parquet')
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), tmp_path / 'new.parquet')
    return pq.ParquetFile(tmp_path / 'old.parquet'), pq.ParquetFile(tmp_path / 'new.parquet')


def test_complete_document_values_allow_incidental_table_order_changes(tmp_path):
    with ExitStack() as owners:
        old, new = [owners.enter_context(file) for file in files(tmp_path, list(reversed(ROWS)))]
        qualify_complete_values(old, new, 'documents')


@pytest.mark.parametrize('change', ['field', 'canonical', 'omission', 'duplicate', 'new-field', 'type'])
def test_document_qualification_refuses_every_changed_field_mapping_and_count(tmp_path, change):
    rows, schema = deepcopy(ROWS), SCHEMA
    if change == 'field':
        rows[0]['values'] = ['same', None, 'same']
    elif change == 'canonical':
        rows[0]['source_id'] = 'different-canonical-source'
    elif change == 'omission':
        rows.pop()
    elif change == 'duplicate':
        rows[1] = rows[0]
    elif change == 'new-field':
        schema = schema.append(pa.field('new', pa.list_(pa.string())))
        rows[0]['new'] = ['unreviewed']
    elif change == 'type':
        schema = pa.schema([('document_id', pa.string()), ('source_id', pa.string()), ('values', pa.large_list(pa.string()))])
    with ExitStack() as owners:
        old, new = [owners.enter_context(file) for file in files(tmp_path, rows, schema)]
        with pytest.raises(ValueError, match='qualification'):
            qualify_complete_values(old, new, 'documents')


def test_retained_source_cursor_must_match_its_current_proof_requirements():
    from congress_api.retention.source_update_proof import retain_source_update, read_source_update
    store = MemoryStore()
    proof = retain_source_update(store, base=dict(selector_sha256=None, selected_ref=None), before=None,
        after=dict(requirements={'stale': 'rules'}), schema=SCHEMA, replacements=[], deletions=[])
    with pytest.raises(ValueError, match='requirements differ'):
        read_source_update(store, proof)
