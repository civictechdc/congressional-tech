"""Offline journal fixture: actual local durability, modeled SDK latency."""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--checkout',type=Path,required=True)
parser.add_argument('--telemetry',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--arm',required=True)
parser.add_argument('--trial',type=int,required=True)
parser.add_argument('--count',type=int,default=1000)
parser.add_argument('--latency-ms',type=float,default=1)
args=parser.parse_args()
root=args.checkout.resolve()
sys.path[:0]=[str(path) for path in sorted((root/'packages').glob('*/src'))]+[str(root/'packages/viewer_publication/tests'),str(args.telemetry)]
from publication_costs import PublicationCosts
from test_publication_capacity import Remote, asset_name
from viewer_publication.continuation import Continuation, DurableJournal
from viewer_publication.client import ContinuedPublicationClient

args.output.mkdir(parents=True)
metrics=PublicationCosts(args.output)
latency=args.latency_ms/1000
class TimedRemote(Remote):
    def put_object(self,**options):
        with metrics.request('put',options['Key']):
            time.sleep(latency)
            result=super().put_object(**options)
            metrics.add({'put_body_bytes':len(options['Body'])})
            return result
    def get_object(self,**options):
        with metrics.request('get',options['Key']):
            time.sleep(latency)
            result=super().get_object(**options)
            metrics.add({'get_body_bytes':result['ContentLength']})
            return result
    def head_object(self,**options):
        with metrics.request('head',options['Key']):
            time.sleep(latency)
            return super().head_object(**options)
    def get_paginator(self,name):
        real=super().get_paginator(name)
        class Pages:
            def paginate(self,**options):
                for page in real.paginate(**options):
                    with metrics.request('list',options['Prefix']):
                        time.sleep(latency)
                    yield page
        return Pages()

def six_workers(action,items):
    items=iter(items)
    pending=set()
    maximum=0
    with ThreadPoolExecutor(max_workers=6) as pool:
        while True:
            while len(pending)<6:
                item=next(items,None)
                if item is None:break
                pending.add(pool.submit(action,item))
                maximum=max(maximum,len(pending))
            if not pending:break
            ready,pending=wait(pending,return_when=FIRST_COMPLETED)
            for future in ready:future.result()
    return maximum

remote=TimedRemote()
binding={'fixture':'journal-scale-1000','source_sha256':'a'*64,'files':args.count}
log_binding={'preparation_sha256':'b'*64,'artifact':{'id':'fixture'},'release_plan':{'release':'releases/'+'c'*32+'/'}}
keys=['viewer-publications/'+asset_name(index) for index in range(args.count)]
started=time.perf_counter()
with metrics.instrument():
    with metrics.stage('upload'):
        original=Continuation(args.output/'original',binding)
        journal=DurableJournal(remote,'bucket',original,'scale-fixture',log_binding)
        proxy=ContinuedPublicationClient(remote,continuation=original,guard=lambda:None,journal=journal.record,after_write=lambda *_:None)
        window=six_workers(lambda key:proxy.put_object(Bucket='bucket',Key=key,Body=b'x',IfNoneMatch='*'),keys)
        journal.record('publication_completed',{'status':'fixture'})
    with metrics.stage('restore_fresh_local_state'):
        fresh=Continuation(args.output/'fresh',binding)
        restored=DurableJournal(remote,'bucket',fresh,'scale-fixture',log_binding,resume=True)
        assert len(fresh.value['writes'])==args.count
        assert all(value['verified'] for value in fresh.value['writes'].values())
        before_reconcile=(remote.gets,remote.puts,remote.heads)
        fresh.reconcile(remote,'bucket',progress=lambda _:None)
        assert (remote.gets,remote.puts,remote.heads)==before_reconcile
    with metrics.stage('replay_acknowledged_payloads'):
        before_replay=(remote.gets,remote.puts,remote.heads)
        proxy=ContinuedPublicationClient(remote,continuation=fresh,guard=lambda:None,journal=restored.record,after_write=lambda *_:None)
        replay_window=six_workers(lambda key:proxy.put_object(Bucket='bucket',Key=key,Body=b'x',IfNoneMatch='*'),keys)
        assert (remote.gets,remote.puts,remote.heads)==before_replay
source_files=['packages/viewer_publication/src/viewer_publication/continuation.py','packages/viewer_publication/src/viewer_publication/client.py','packages/viewer_publication/tests/test_publication_capacity.py']
inputs={'arm':args.arm,'trial':args.trial,'checkout':str(root),'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),
 'source_files_sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in source_files},
 'telemetry_file':str(args.telemetry/'publication_costs.py'),'telemetry_sha256':hashlib.sha256((args.telemetry/'publication_costs.py').read_bytes()).hexdigest(),
 'rss_sampler_sha256':hashlib.sha256((args.telemetry/'process_rss.py').read_bytes()).hexdigest(),
 'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'python':sys.executable,'count':args.count,'payload_bytes':1,'workers':6,'sdk_request_latency_ms':args.latency_ms,
 'local_evidence_saves_and_fsync':'real; no mocked writes','fixture_limit':'no production network/artifact/native preparation'}
outcomes={'payload_writes':args.count,'journal_events':restored.sequence,'journal_bytes':restored.total_bytes,'payload_replays':args.count,'max_upload_window':window,'max_replay_window':replay_window,
 'replay_payload_put_get_head_delta':[0,0,0],'uncertain_payload_reads':0,'total_wall_seconds':round(time.perf_counter()-started,6)}
metrics.save(args.output/'receipt.json',inputs=inputs,outcomes=outcomes)
print(json.dumps({'arm':args.arm,'trial':args.trial,'receipt':str(args.output/'receipt.json'),'outcomes':outcomes,'stages':[{k:stage[k] for k in ('stage','seconds','counts')} for stage in metrics.stages]}))
