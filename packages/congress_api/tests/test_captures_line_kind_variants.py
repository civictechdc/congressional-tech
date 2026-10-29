"""Full-corpus record variants preserve each inline item and refuse new shapes."""
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from congress_api.lake import captures
from test_captures_ingest import ingest

ROOT=Path(captures.__file__).resolve().parents[5]
CASES=json.loads((ROOT/'model/fixtures/receipt-line-kind-variants.json').read_text())

def key(family):return f'receipts/{family}/undated/assemble-20260930.jsonl.gz'

@pytest.mark.parametrize('case',CASES,ids=[c['id'] for c in CASES])
def test_every_new_record_shape_preserves_its_own_rows(tmp_path,case):
    stage=ingest(tmp_path,[dict(record=case['record'])],key=key(case['family']))
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['outcome'] for r in rows]==case['outcomes']
    assert [r['url'] for r in rows]==[r['requested_url'] for r in rows]==case['urls']
    assert [r['capture_index'] for r in rows]==list(range(len(rows)))
    assert all(r['sha256'] is None and r['http_status'] is None and r['retrieved_at'] is None for r in rows)
    assert pq.read_table(stage/'capture-evidence.parquet')['source_record_index'].to_pylist()==list(range(len(rows)))

@pytest.mark.parametrize(('family','record'),[
    ('documents',[['https://fixture.test/a.pdf','not-a-digest']]),
    ('documents',[['https://fixture.test/a.pdf','a'*64,'extra']]),
    ('documents',[['not-a-url','a'*64]]),
    ('documents',['FbncCf4rh8E']),
    ('youtube/captions',['not an identifier']),
    ('youtube/captions',['https://fixture.test/unknown']),
    ('youtube/captions',[[]]),
    ('not-enumerated',[]),
    ('documents',dict(url='ttps://www.gpo.gov/unlisted.pdf')),
    ('documents',[['relative.html','a'*64]]),
])
def test_unregistered_shape_and_malformed_pair_still_refuse(tmp_path,family,record):
    with pytest.raises(ValueError,match='unknown record-only line kind'):
        ingest(tmp_path,[dict(record=record)],key=key(family))
    assert not (tmp_path/'stage/ingested-receipts.json').exists()


def test_identifier_list_keeps_explicit_line_failure(tmp_path):
    stage=ingest(tmp_path,[dict(record=['FbncCf4rh8E','FsSGuBPdBKQ'],outcome='request_failed',http_status=503)],key=key('youtube/captions'))
    rows=pq.read_table(stage/'captures.parquet').to_pylist()
    assert [r['outcome'] for r in rows]==['retry_later']*2
    assert [r['http_status'] for r in rows]==[503]*2
