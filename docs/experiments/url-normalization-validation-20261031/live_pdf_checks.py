"""Finish full-body and parser checks for the five successful trim candidates."""
from common import *
import concurrent.futures,httpx,subprocess,datetime
jobs=[x for x in json.loads((OUT/'live-trim-results.json').read_text())['results'] if x.get('pdf_header')]
def check(job):
 r={'target':job['target'],'url':job['url'],'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 try:
  with httpx.Client(timeout=20,follow_redirects=True,max_redirects=6) as client:
   with client.stream('GET',job['url']) as response:
    response.raise_for_status();parts=[];size=0
    for chunk in response.iter_bytes(65536):
     size+=len(chunk)
     if size>25*1024*1024:raise ValueError('audit size bound')
     parts.append(chunk)
    body=b''.join(parts);sha=hashlib.sha256(body).hexdigest();path=OUT/'live-trim'/(sha+'.pdf');path.write_bytes(body)
    p=subprocess.run(['/opt/homebrew/bin/pdftotext','-f','1','-l','1',str(path),'-'],capture_output=True,timeout=15)
    r.update(status=response.status_code,final_url=str(response.url),bytes=len(body),sha256=sha,path=str(path),pdf_header=body.startswith(b'%PDF-'),text_exit=p.returncode,first_page=p.stdout.decode('utf-8',errors='replace')[:6000])
 except Exception as e:r['error']=type(e).__name__+': '+str(e)
 return r
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(check,jobs))
c=connect()
for r in results:
 r['already_published_body']=bool(c.execute('SELECT count(*) FROM docs WHERE lower(hex(saved_body))=?',[r.get('sha256')]).fetchone()[0])
dump('live-pdf-results.json',results)
print(json.dumps(results,indent=2))
