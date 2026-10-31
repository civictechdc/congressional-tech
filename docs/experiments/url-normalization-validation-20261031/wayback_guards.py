"""Negative controls derived from a retained CDX row and verified replay body."""
from common import *
import copy
from corpus_recovery.cdx import key
from corpus_recovery import discovery as baseline

ns={'__name__':'corpus_recovery.experimental_discovery','key':key}
exec(compile((OUT/'proposed-discovery.py').read_text(),str(OUT/'proposed-discovery.py'),'exec'),ns)
candidate=json.loads((OUT/'wayback-candidates.json').read_text())[0]
fields=['urlkey','timestamp','original','mimetype','statuscode','digest','length']
base={'urlkey':key(candidate['target_url']),'timestamp':candidate['timestamp'],'original':candidate['original_url'],
 'mimetype':'application/pdf','statuscode':'200','digest':candidate['digest'],'length':'1'}
results=[]
def index_case(name,mutate=lambda x:None,*,complete=True,status=200,redirect=False,**kwargs):
 row=copy.deepcopy(base);mutate(row)
 def call(kind,url):
  return ns['Response'](status,json.dumps([fields,[row[k] for k in fields]]).encode(),complete,'controlled-retained-row',final_url=url+'/redirect' if redirect else url)
 r=ns['wayback_lookup'](candidate['target_url'],call,max_pages=1,**kwargs)
 results.append({'case':name,'reason':r['reason'],'candidates':len(r['candidates']),'complete':r['complete']})
 return r
assert index_case('retained_alias')['complete']
for name,fn in [('wrong_surt',lambda r:r.update(urlkey='com,example)/wrong')),
 ('wrong_original',lambda r:r.update(original='https://example.com/wrong.pdf')),
 ('wrong_status',lambda r:r.update(statuscode='404')),
 ('invalid_timestamp',lambda r:r.update(timestamp='20261301000000'))]:
 assert not index_case(name,fn)['complete']
assert not index_case('outside_window',from_timestamp='2099')['complete']
assert not index_case('truncated_response',complete=False)['complete']
assert not index_case('rate_limit',status=429)['complete']
assert not index_case('redirected_index',redirect=True)['complete']
rep=json.loads((OUT/'wayback-results.json').read_text())['retained_verified_replays'][0]
real=next(c for c in json.loads((OUT/'wayback-candidates.json').read_text()) if c['url']==rep['replay'])
body=Path(rep['body_path']).read_bytes()
def replay_case(name,*,data=body,status=200,complete=True,final=None,digest=real['digest'],timestamp=real['timestamp']):
 try:
  baseline.acquire_wayback(real['url'],real['original_url'],timestamp,
   lambda kind,url:baseline.Response(status,data,complete,rep['body_path'],final_url=final or url),digest=digest)
  accepted=True;error=None
 except ValueError as e:accepted=False;error=str(e)
 results.append({'case':name,'accepted':accepted,'error':error})
 return accepted
assert replay_case('retained_replay')
assert not replay_case('wrong_body_digest',data=body+b'audit-control')
assert not replay_case('redirected_replay',final='https://example.com/redirect')
assert not replay_case('wrong_replay_timestamp',timestamp='20000101000000')
assert not replay_case('incomplete_replay',complete=False)
assert not replay_case('error_replay',status=404)
dump('wayback-guard-results.json',{'control_basis':'Real retained alias row and replay bytes; named fields changed only for negative controls.','results':results})
print(json.dumps(results,indent=2))
