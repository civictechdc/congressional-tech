"""Unknown record checks apply to retained rows after primary reference coverage."""
import pyarrow.parquet as pq
import pytest
from test_captures_ingest import body,ingest


def test_covered_temporary_item_placeholder_does_not_invent_a_record_row(tmp_path):
    stage=ingest(tmp_path,[dict(record=[dict(url='https://fixture.test/a'),dict(url='https://fixture.test/b')],
        captures=[body(pointer=[0,'body']),body(pointer=[1,'body'])])])
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert len(rows)==2 and [r['capture_index'] for r in rows]==[0,1]
    assert [r['url'] for r in rows]==['https://fixture.test/a','https://fixture.test/b']
    assert all(r['sha256'] is not None and r['outcome']=='stored' for r in rows)


def test_uncovered_unknown_item_still_refuses_before_acceptance(tmp_path):
    with pytest.raises(ValueError,match='unknown record-only line kind'):
        ingest(tmp_path,[dict(record=[dict(url='https://fixture.test/a'),dict(url='https://fixture.test/b')],
            captures=[body(pointer=[0,'body'])])])
    assert not (tmp_path/'stage/ingested-receipts.json').exists()
