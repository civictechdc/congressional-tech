"""Bounded current HTTP check; response prefixes do not establish full integrity."""
from common import *
import asyncio,httpx,re,datetime
from urllib.parse import urlsplit,urlunsplit
c=connect()
targets=rows(c,"""SELECT DISTINCT n.url,n.baseline_fetch FROM normalized n JOIN k ON n.url=k.target_url
 WHERE n.baseline_key IS DISTINCT FROM n.proposed_key AND regexp_matches(n.baseline_key,'%20+$') ORDER BY n.url""")
c.close();work=OUT/'live-trim';work.mkdir(exist_ok=True)
jobs=[]
for target in targets:
 p=urlsplit(target['baseline_fetch']);clean=urlunsplit((p.scheme,p.netloc,re.sub('(?:%20)+$','',p.path),p.query,''))
 for arm,url in [('literal',target['baseline_fetch']),('trimmed',clean)]:jobs.append({'target':target['url'],'arm':arm,'url':url})
async def main():
 semaphore=asyncio.Semaphore(2)
 async with httpx.AsyncClient(timeout=10,follow_redirects=True,max_redirects=6,headers={'User-Agent':'Congressional-Tech-URL-Validation/1.0'}) as client:
  async def capture(job):
   r=dict(job,checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
   async def transfer():
    async with client.stream('GET',job['url']) as response:
     r.update(status=response.status_code,final_url=str(response.url),content_type=response.headers.get('content-type'),content_length=response.headers.get('content-length'),
      redirects=[{'status':x.status_code,'url':str(x.url),'location':x.headers.get('location')} for x in response.history])
     buf=bytearray();complete=True
     async for block in response.aiter_bytes(16384):
      buf.extend(block)
      if len(buf)>=65536:buf=buf[:65536];complete=False;break
     body=bytes(buf);sha=hashlib.sha256(body).hexdigest();path=work/(sha+'.prefix');path.write_bytes(body)
     title=re.search(r'<title[^>]*>(.*?)</title',body.decode('utf-8',errors='replace'),re.I|re.S)
     r.update(prefix_bytes=len(body),complete_body=complete,prefix_sha256=sha,prefix_path=str(path),pdf_header=body.startswith(b'%PDF-'),title=title[1].strip() if title else None)
   async with semaphore:
    try:await asyncio.wait_for(transfer(),20)
    except Exception as e:r.update(error=type(e).__name__+': '+str(e))
   print(job['arm'],r.get('status'),r.get('pdf_header'),job['url'],flush=True)
   return r
  results=await asyncio.gather(*(capture(j) for j in jobs))
 dump('live-trim-results.json',{'method':'Fresh paired GET requests, concurrency 2, maximum 20 seconds per URL and 64 KiB decoded response prefix. Not a full document validation.','target_count':len(targets),'results':results})
asyncio.run(main())
