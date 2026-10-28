"""Five owner-fetched parent bodies pass the same conditional range adapter."""
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from congress_api.lake.readings import parse_once_payload
from congress_api.retention.r2 import R2Store
from test_readings_ranged import Client,payload,phase


FIXTURES=Path(__file__).parent/'fixtures/ranged-parent-bodies'
EXPECTED=json.loads((FIXTURES/'expected.json').read_text())


@pytest.mark.parametrize('expected',EXPECTED,ids=[r['sha256'][:8] for r in EXPECTED])
def test_fetched_parent_format_custody_and_disjoint_full_page_read(tmp_path,expected):
    stored=(FIXTURES/(expected['sha256']+'.gz')).read_bytes()
    assert len(stored)==expected['stored_bytes'] and hashlib.md5(stored).hexdigest()==expected['stored_md5']
    entity=gzip.decompress(stored)
    assert hashlib.sha256(entity).hexdigest()==expected['sha256']
    client=Client(stored);store=R2Store(client,'bucket')
    with phase(tmp_path):
        result=parse_once_payload(payload(tmp_path,entity,stored,suffix='.gz',stored_gzip=True),body_store=store)
    assert [(r['parser'],r['status']) for r in result['rows']]==[('sniff','completed'),('html','completed')]
    assert result['rows'][0]['format']==expected['format'] and result['read_bytes']==len(stored)
    intervals=sorted(tuple(map(int,r['Range'][6:].split('-'))) for r in client.reads)
    assert intervals[0][0]==0 and intervals[-1][1]==len(stored)-1
    assert all(left[1]+1==right[0] for left,right in zip(intervals,intervals[1:]))
