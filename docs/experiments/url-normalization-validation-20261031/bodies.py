from common import *
import gzip,re,subprocess,concurrent.futures,collections
from urllib.parse import unquote
c=connect();selected=rows(c,"SELECT * FROM repairs WHERE ends_with(target_url,'&download=1')");c.close()
store=CAM/'track_b/raw_store';bysha={}
for r in selected:bysha.setdefault(r['body_sha256'],[]).append(r)
def check(item):
 sha,targets=item;path=store/'bodies/sha256'/sha[:2]/sha
 result={'sha256':sha,'targets':[r['target_url'] for r in targets],'path':str(path),'exists':path.exists()}
 if not path.exists():return result
 body=path.read_bytes();result.update(bytes=len(body),sha256_matches=hashlib.sha256(body).hexdigest()==sha,pdf_header=body.startswith(b'%PDF-'))
 bindings=[]
 for r in targets:
  receipt=store/r['receipt_key']
  records=[json.loads(line) for line in gzip.open(receipt,'rt')]
  match=[line for line in records if line['url']==r['candidate_url'] and any(cap.get('sha256')==sha and cap.get('complete') for cap in line.get('captures',[]))]
  bindings.append({'target':r['target_url'],'final_url':r['candidate_url'],'receipt':str(receipt),'receipt_bound':len(match)==1,
   'repaired_requested_url':bool(match) and match[0]['requested_url']==re.sub(r'(?:%20|\s)*&download=1$','?download=1',r['target_url']),
   'redirects':match[0].get('redirects') if match else None,'intact':all(cap.get('intact') is True for line in match for cap in line['captures'] if cap.get('sha256')==sha)})
 result['bindings']=bindings
 try:
  p=subprocess.run(['/opt/homebrew/bin/pdftotext','-f','1','-l','1','-','-'],input=body,capture_output=True,timeout=15)
  text=p.stdout.decode('utf-8',errors='replace');result.update(text_exit=p.returncode,text=text[:12000],text_chars=len(text),parse_diagnostic=p.stderr.decode('utf-8',errors='replace')[:400])
  tokens=set(re.findall(r'[a-z0-9]{4,}',unquote(targets[0]['target_url'].rsplit('/',1)[-1]).lower()))-{'download','testimony','statement','witness','opening','hearing','chairwoman','chairman'}
  result['slug_tokens_found']=sorted(t for t in tokens if t in text.lower());result['slug_tokens']=sorted(tokens)
 except subprocess.TimeoutExpired:result['text_timeout']=True
 return result
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
 for i,r in enumerate(pool.map(check,bysha.items()),1):
  results.append(r)
  if i%200==0:print('checked unique bodies',i,flush=True)
dump('repair-body-checks.json',results)
summary={'targets':len(selected),'unique_bodies':len(results),'available':sum(r['exists'] for r in results),'hash_matches':sum(r.get('sha256_matches',False) for r in results),
 'pdf_headers':sum(r.get('pdf_header',False) for r in results),'text_success':sum(r.get('text_exit')==0 for r in results),'text_nonempty':sum(r.get('text_chars',0)>10 for r in results),
 'receipt_bound_targets':sum(b['receipt_bound'] for r in results for b in r.get('bindings',[])),'repaired_requested_targets':sum(b['repaired_requested_url'] for r in results for b in r.get('bindings',[])),
 'first_page_slug_corroboration':sum(bool(r.get('slug_tokens_found')) for r in results),'bytes_read':sum(r.get('bytes',0) for r in results),
 'duplicate_bodies':[r for r in results if len(r['targets'])>1],
 'weak_examples':[{k:v for k,v in r.items() if k!='bindings'} for r in results if not r.get('slug_tokens_found')][:20]}
dump('repair-body-summary.json',summary);print(json.dumps({k:v for k,v in summary.items() if k not in ('duplicate_bodies','weak_examples')},indent=2))
