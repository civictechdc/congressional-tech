import duckdb, os, sys, time, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor
O='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/page-versions/'
BASE='https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/'
DL=O+'downloads/'
os.makedirs(DL, exist_ok=True)
c=duckdb.connect()
QUOTA={'senate_hearing_page':400,'veterans_statement':300,'house_news_statement':150,'file_shaped_url':100,'gpo_transcript':100}
c.sql(f"create table u as select * from '{O}urls_html_strata.parquet'")
c.sql(f"create table b as select * from '{O}bodies_html.parquet'")
parts=[]
for s,n in c.sql("select coalesce(stratum,'other'), count(*) from u group by 1").fetchall():
    q=QUOTA.get(s,n)
    parts.append(f"(select * from u where coalesce(stratum,'other')='{s}' order by hash(context_url || 'pv1') limit {q})")
c.sql("create table s as " + " union all ".join(parts))
c.sql(f"copy s to '{O}sample_html.parquet'")
mode=sys.argv[1] if len(sys.argv)>1 else 'html'
if mode=='bin':
    keys=[r[0] for r in c.sql(f"select distinct body_key from '{O}bodies_bin.parquet'").fetchall()]
else:
    # cap per-URL bodies at 6 (the 18-body URL)
    keys=[r[0] for r in c.sql("select distinct body_key from (select b.*, row_number() over (partition by b.context_url order by first_seen) rn from b join s using(context_url)) where rn<=6").fetchall()]
print('fetches', len(keys), flush=True)
lock=threading.Lock(); last=[0.0]
def gate():
    with lock:
        wait=last[0]+0.21-time.time()
        if wait>0: time.sleep(wait)
        last[0]=time.time()
def get(k):
    path=DL+k.split('/')[-1]
    if os.path.exists(path): return 'cached'
    for attempt in range(3):
        gate()
        try:
            req=urllib.request.Request(BASE+k, headers={'User-Agent':'congressional-tech-review/1.0'})
            with urllib.request.urlopen(req, timeout=60) as r: data=r.read()
            open(path+'.part','wb').write(data); os.rename(path+'.part', path); return 'ok'
        except Exception as e:
            err=repr(e)
            if '404' in err: return 'missing'
            time.sleep(2)
    return 'fail '+err
from collections import Counter
cnt=Counter()
with ThreadPoolExecutor(4) as ex:
    for i,res in enumerate(ex.map(get, keys)):
        cnt[res.split()[0]]+=1
        if i%200==0: print(i, dict(cnt), flush=True)
print('done', dict(cnt), flush=True)
