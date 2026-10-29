"""Optional measurements time maintained reads through full stream consumption."""
import json
import io
import pytest

from congress_api.lake import readings
from congress_api.retention.r2 import R2Store
from test_readings_ranged import Client,payload,phase
from test_r2_body_files import Client as WholeClient,DATA,KEY
import hashlib


def test_range_timings_name_only_physical_reads_and_preserve_cache_retry(tmp_path):
    data=b'%PDF-1.7\n'+b'x'*24000+b'%%EOF';client=Client(data);store=R2Store(client,'bucket')
    request=json.loads(payload(tmp_path,data,data));request['request_timings']=True
    with phase(tmp_path):
        first=readings.parse_once_payload(json.dumps(request).encode(),body_store=store)
        again=readings.parse_once_payload(json.dumps(request).encode(),body_store=store)
    assert first['rows']==again['rows'] and len(client.reads)==2
    assert [r['start'] for r in first['read_timings']]==[0,len(data)-8192]
    assert all(r['seconds']>=0 and r['bytes']==8192 and r['requests']==1 and r['error_type'] is None
        for r in first['read_timings'])
    assert again['read_timings']==[]
    assert all('key' not in row and 'etag' not in row for row in first['read_timings'])


@pytest.mark.parametrize('short',[False,True])
def test_pinned_prefetch_collects_completed_read_and_failure_timings(tmp_path,short):
    client=WholeClient();client.meta.config.retries={'total_max_attempts':1}
    client.responses=[dict(Body=io.BytesIO(DATA[:-1] if short else DATA),ContentLength=len(DATA),
        ETag='"'+hashlib.md5(DATA).hexdigest()+'"')]
    store=R2Store(client,'bucket',cache_dir=tmp_path/'cache');timings=[]
    args=dict(expected={KEY:dict(md5=hashlib.md5(DATA).hexdigest(),bytes=len(DATA))},timings=timings)
    if short:
        with pytest.raises(ValueError,match='Incomplete'):store.prefetch_immutable([KEY],**args)
    else:store.prefetch_immutable([KEY],**args)
    assert len(timings)==1 and timings[0]['seconds']>=0 and timings[0]['requests']==1
    assert timings[0]['error_type']==('ValueError' if short else None)
    assert timings[0]['bytes']==(0 if short else len(DATA))
    assert timings[0]['key']==KEY


def test_timing_preserves_sdk_retry_metadata_separately_from_stream_attempts(tmp_path):
    client=WholeClient();client.meta.config.retries={'total_max_attempts':1}
    client.responses=[dict(Body=io.BytesIO(DATA),ContentLength=len(DATA),ETag='"'+hashlib.md5(DATA).hexdigest()+'"',
        ResponseMetadata={'RetryAttempts':2})]
    timing={}
    assert R2Store(client,'bucket').read(KEY,expected=dict(md5=hashlib.md5(DATA).hexdigest(),bytes=len(DATA)),timing=timing)==DATA
    assert timing['requests']==1 and timing['sdk_retries']==2
