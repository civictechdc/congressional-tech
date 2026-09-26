import requests, json, os, sys, time, threading
from concurrent.futures import ThreadPoolExecutor
S=sys.argv[1]; K=open(f'{S}/.dgkey').read().strip()
OUT=f'{S}/meetings.jsonl'
done=set()
if os.path.exists(OUT):
    for l in open(OUT):
        try: done.add(json.loads(l)['_url'])
        except Exception: pass
sess=requests.Session(); lock=threading.Lock()
def get(url, params=None):
    for a in range(6):
        try:
            r=sess.get(url,params={**(params or {}),"api_key":K,"format":"json"},timeout=60)
            if r.status_code==200: return r.json()
            if r.status_code in (429,500,502,503,504): time.sleep(2**a*3); continue
            return {"_status":r.status_code}
        except Exception: time.sleep(2**a)
    return {"_status":"failed"}
urls=[]
for c in range(112,120):
    for ch in ['house','nochamber']:
        off=0
        while True:
            d=get(f"https://api.congress.gov/v3/committee-meeting/{c}/{ch}",{"limit":250,"offset":off})
            ms=d.get('committeeMeetings',[])
            urls+= [m['url'].split('?')[0] for m in ms]
            off+=250
            if len(ms)<250: break
urls=[u for u in dict.fromkeys(urls) if u not in done]
print('to fetch',len(urls),'already',len(done),flush=True)
out=open(OUT,'a'); n=0
def one(u):
    global n
    d=get(u)
    rec=d.get('committeeMeeting') or {"_status":d.get('_status')}
    rec['_url']=u
    with lock:
        out.write(json.dumps(rec)+'\n'); n+=1
        if n%500==0: out.flush(); print('fetched',n,flush=True)
with ThreadPoolExecutor(5) as p: list(p.map(one,urls))
out.close(); print('DONE',n,flush=True)
