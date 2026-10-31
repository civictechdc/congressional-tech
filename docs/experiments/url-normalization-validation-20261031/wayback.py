from common import *
import collections,types
from urllib.parse import parse_qs,urlsplit
from corpus_recovery import discovery as baseline
from corpus_recovery.cdx import key

source=Path(baseline.__file__).read_text()
source=source.replace("if not isinstance(data, list) or not data or data[0] != fields:","if data == []:\n        return [], None\n    if not isinstance(data, list) or not data or data[0] != fields:")
source=source.replace("if (row['original'] != original or row['statuscode'] != '200'", "if (not _source_url(row['original']) or key(original) is None or row['urlkey'] != key(original) or key(row['original']) != key(original) or row['statuscode'] != '200'")
source=source.replace("/{original}\"\n            ident = (row['timestamp'], original, row['digest'])", "/{row['original']}\"\n            ident = (row['timestamp'], row['original'], row['digest'])")
source=source.replace("'original_url': original,\n                                 'timestamp': row['timestamp']", "'original_url': row['original'],\n                                 'timestamp': row['timestamp']")
(OUT/'proposed-discovery.py').write_text(source)
namespace={'__name__':'corpus_recovery.experimental_discovery','key':key};exec(compile(source,str(OUT/'proposed-discovery.py'),'exec'),namespace)
folder=CAM/'track_b/b2_discovery'
qualified=json.loads((folder/'all_wayback_qualified.json').read_text())
details=[];candidates=[];retained={}
for p in sorted(folder.rglob('downloaded.json')):
 final=json.loads(p.read_text())['final']
 if final.get('body') and Path(final['body']['path']).exists():retained[final['requested_url']]=(p,final)
 if not final['requested_url'].startswith('https://web.archive.org/cdx/'):continue
 original=parse_qs(urlsplit(final['requested_url']).query)['url'][0]
 body=Path(final['body']['path']).read_bytes() if final.get('body') else b''
 if final.get('body'):assert hashlib.sha256(body).hexdigest()==final['body']['sha256']
 def run(module):
  Response=module['Response']
  def capture(kind,url):
   assert url==final['requested_url']
   return Response(final['http_status'],body,final['complete'],str(p),final.get('headers',{}).get('content-type',''),final.get('url'))
  return module['wayback_lookup'](original,capture,max_pages=1,page_size=20)
 old=run(vars(baseline));new=run(namespace)
 details.append(dict(target=original,status=final['http_status'],before=old['reason'],after=new['reason'],before_candidates=len(old['candidates']),after_candidates=len(new['candidates']),evidence=str(p)))
 if old['reason']=='invalid_index_response': candidates.extend(new['candidates'])
dump('wayback-candidates.json',candidates)
# Verify actual retained replay bytes where a qualifying replay already exists.
replays=[]
for candidate in candidates:
 q=[r for r in qualified if r['replay_url']==candidate['url']]
 if not q:continue
 for r in q:
  item={'target':candidate['target_url'],'replay':candidate['url'],'body_sha256':r['body_sha256'],'qualification_sha256':r['qualification_sha256']}
  matched=retained.get(candidate['url'])
  path=Path(matched[1]['body']['path']) if matched else folder/'extra_replays'/f"{r['body_sha256']}.body"
  if not path.exists():
   path=CAM/'track_b/raw_store/bodies/sha256'/r['body_sha256'][:2]/r['body_sha256']
  item['body_path']=str(path);item['body_available']=path.exists()
  if path.exists():
   body=path.read_bytes();assert hashlib.sha256(body).hexdigest()==r['body_sha256']
   baseline._verify_digest(body,candidate['digest'])
   item['sha256_verified']=True;item['cdx_digest_verified']=True;item['pdf_header']=body.startswith(b'%PDF-');item['bytes']=len(body)
   item['exact_replay_validation']=baseline.validate_wayback_replay(candidate['url'],candidate['original_url'],candidate['timestamp'])
   if matched:
    p,f=matched
    baseline.acquire_wayback(candidate['url'],candidate['original_url'],candidate['timestamp'],lambda kind,url:baseline.Response(f['http_status'],body,f['complete'],str(p),f['headers'].get('content-type',''),f['url']),digest=candidate['digest'])
    item['actual_acquisition_validation']=True
  replays.append(item)
# Pagination control: retained real data rows, with a constructed resume trailer
# and an actual retained empty page. This tests state retention, not archive yield.
nonempty=next(v for v in retained.values() if v[1]['requested_url'].startswith('https://web.archive.org/cdx/') and v[1]['http_status']==200 and len(json.loads(Path(v[1]['body']['path']).read_bytes()))>1)
raw=json.loads(Path(nonempty[1]['body']['path']).read_bytes());parsed,_=baseline._wayback_page(json.dumps(raw).encode())
first=json.dumps([raw[0]]+[[r[k] for k in raw[0]] for r in parsed]+[[],['audit-resume']]).encode()
target=parse_qs(urlsplit(nonempty[1]['requested_url']).query)['url'][0]
calls=[]
def pages(kind,url):
 calls.append(url);return namespace['Response'](200,first if len(calls)==1 else b'[]',True,'retained-body-with-constructed-pagination',final_url=url)
pagination=namespace['wayback_lookup'](target,pages,max_pages=2,page_size=20)
dump('wayback-pagination-debug.json',{'pagination':pagination,'raw':raw,'target':target,'replays':replays,'details':details})
assert pagination['complete'] and len(pagination['evidence'])==2 and len(pagination['candidates'])==len({(r['timestamp'],r['original'],r['digest']) for r in parsed})
summary={'transitions':[dict(before=k[0],after=k[1],http_status=k[2],calls=v) for k,v in collections.Counter((r['before'],r['after'],r['status']) for r in details).items()],
 'new_candidate_rows':len(candidates),'new_candidate_targets':len({r['target_url'] for r in candidates}),
 'retained_verified_replays':replays,'details':details,'pagination_control':{'complete':pagination['complete'],'evidence_pages':len(pagination['evidence']),'candidates_preserved':len(pagination['candidates']),'constructed_resume_trailer':True}}
dump('wayback-results.json',summary)
print(json.dumps({k:v for k,v in summary.items() if k not in ('details','retained_verified_replays')},indent=2));print('retained verified replays',len(replays))
