"""Real read/worker/stage consumers retain safe diagnostics without settling failed input."""
import hashlib
import io
import json
from pathlib import Path

from body_text_fixtures import committed, lake
from congress_api.lake import body_text
from congress_api.retention.r2 import R2Store
from test_r2_body_files import Client as BaseClient


def test_raw_range_failures_survive_worker_serialization_and_native_stage(tmp_path,monkeypatch):
    secret='https://credentials.invalid/?token=DO_NOT_RETAIN'
    kinds=('length','etag','range','short','request_value','body_value','good')
    bodies={name:(f'<doc>Useful source text {name}.</doc>'.encode(),'xml') for name in kinds}
    args,names=lake(tmp_path,bodies)
    args.pop('local_root')
    data={digest.hex():bodies[name][0] for digest,name in names.items()}
    labels={digest.hex():name for digest,name in names.items()}
    streams=[]

    class BrokenStream(io.BytesIO):
        def read(self,*args):raise ValueError(secret)

    class Client(BaseClient):
        def get_object(self,**kwargs):
            self.reads.append(kwargs)
            digest=kwargs['Key'].rsplit('/',1)[-1]
            kind,value=labels[digest],data[digest]
            if kind=='request_value':raise ValueError(secret)
            stream=(BrokenStream(value) if kind=='body_value' else
                    io.BytesIO(value[:-1] if kind=='short' else value))
            streams.append(stream)
            return dict(Body=stream,ContentLength=len(value)+(kind=='length'),
                ETag='"'+('0'*32 if kind=='etag' else hashlib.md5(value).hexdigest())+'"',
                ContentRange=f'bytes 0-{len(value)-1}/{len(value)+(kind=="range")}',
                ResponseMetadata={'HTTPStatusCode':206})

    client=Client();client.meta.config.retries={'total_max_attempts':1}
    store=R2Store(client,'bucket',cache_dir=tmp_path/'object-cache')
    monkeypatch.setattr(body_text,'_origin_store',lambda origin:store)
    monkeypatch.setenv('DOCSPEC_PARSER_IO_MARKER',str(tmp_path/'io-marker'))
    replies=[]

    class Worker:
        """Use the actual callable and JSON wire boundary, injecting only the transport."""
        def __init__(self,*args,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def parse(self,input_id,payload):
            value=body_text.parse_payload(payload)
            if value.get('read_error'):
                cache=Path(json.loads(payload)['cache'])
                assert not list(cache.glob('*.bin')) and not list(cache.glob('*.pending'))
            replies.append(value)
            return json.loads(json.dumps(dict(status='completed',value=value)))

    report=body_text.run(**args,origin=secret,work=tmp_path/'run',execute=True,worker_factory=Worker)
    [batch]=report['batches']
    assert report['status']=='pending' and report['pending_read_reasons']=={'raw_range_ValueError':6}
    outcomes={labels[row['body_sha256']]:row for row in batch['body_outcomes']}
    expected=dict(length=('response_headers','response_metadata_mismatch'),
        etag=('response_headers','response_metadata_mismatch'),range=('response_headers','range_mismatch'),
        short=('response_body','payload_length_mismatch'),request_value=('request','unknown_value_error'),
        body_value=('response_body','unknown_value_error'))
    for name,(phase,reason) in expected.items():
        row=outcomes[name]
        assert (row['status'],row['reading_status'],row['reason'])==('pending',None,'raw_range_ValueError')
        diagnostic=row['raw_read_diagnostic']
        assert (diagnostic['phase'],diagnostic['reason'])==(phase,reason)
        assert diagnostic['expected_total_bytes']==diagnostic['expected_bytes']==len(bodies[name][0])
        assert row['error']=='OSError: raw_range_ValueError'
    assert outcomes['short']['raw_read_diagnostic']['observed_bytes']==len(bodies['short'][0])-1
    assert outcomes['etag']['raw_read_diagnostic']['etag_matches'] is False
    assert outcomes['range']['raw_read_diagnostic']['range_valid'] is False
    assert 'raw_read_diagnostic' not in outcomes['good']
    retained=[json.loads(line) for path in (tmp_path/'run').glob('batch-*/stage/body-outcomes.jsonl')
              for line in path.read_text().splitlines()]
    assert sorted(retained,key=lambda row:row['body_sha256'])==batch['body_outcomes']
    assert secret not in json.dumps([replies,retained])
    assert len(client.reads)==len(kinds) and all(stream.closed for stream in streams)
    assert not list((tmp_path/'object-cache').rglob('*.bin'))
    assert not list((tmp_path/'run').glob('batch-*/stage/bodies/*'))
    assert committed(args,tmp_path/'readings','readings','status')==[
        dict(body=next(key for key,name in labels.items() if name=='good'),status='completed')]
    assert [row['text'] for row in committed(args,tmp_path/'text','body_text','text')]==['Useful source text good.']
    assert body_text.run(**args,origin=secret,work=tmp_path/'again',execute=False)['work_items']==6
