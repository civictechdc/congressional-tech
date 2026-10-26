import duckdb, gzip, os, io, zipfile, json, unicodedata, hashlib, collections, sys, urllib.request, time
from pypdf import PdfReader
import logging; logging.disable(logging.WARNING)
O='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/page-versions/'
DL=O+'downloads/'
c=duckdb.connect()
# union of snapshot bin pop and receipt bin pop (req key)
snap=c.sql(f"select context_url, list(distinct body_key) from '{O}bodies_bin.parquet' group by 1").fetchall()
rec=c.sql(f"select g.req_key, list(distinct g.body_key) from '{O}recpop_bin_req.parquet' p join '{O}good_bin.parquet' g on g.req_key=p.k group by 1").fetchall()
recset={u for u,_ in rec}
allurls={u:set(k) for u,k in snap}
for u,k in rec: allurls.setdefault(u,set()).update(k)
def fetch(k):
    p=DL+k.split('/')[-1]
    if not os.path.exists(p):
        time.sleep(0.25)
        req=urllib.request.Request('https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/'+k, headers={'User-Agent':'congressional-tech-review/1.0'})
        data=urllib.request.urlopen(req,timeout=120).read(); open(p,'wb').write(data)
    return gzip.decompress(open(p,'rb').read())
def info(raw):
    if raw[:4]==b'%PDF':
        intact=b'%%EOF' in raw[-2048:]
        txt=None
        try:
            r=PdfReader(io.BytesIO(raw)); txt=' '.join(unicodedata.normalize('NFKC',' '.join((pg.extract_text() or '') for pg in r.pages)).split())
            npages=len(r.pages)
        except Exception as e: npages=None
        return dict(fmt='pdf', intact=intact, pages=npages, fp=hashlib.sha256(txt.encode()).hexdigest()[:12] if txt else None, tlen=len(txt) if txt else 0, text=txt)
    if raw[:2]==b'PK':
        try:
            z=zipfile.ZipFile(io.BytesIO(raw)); mem=sorted(hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/'))
            return dict(fmt='zip', intact=True, members=len(mem), fp=hashlib.sha256('\n'.join(mem).encode()).hexdigest()[:12], names=sorted(z.namelist())[:5])
        except Exception as e: return dict(fmt='zip', intact=False, err=repr(e)[:80])
    return dict(fmt='other', head=raw[:40].decode('latin1'))
out=[]
for u,keys in sorted(allurls.items()):
    vs=[]
    for k in sorted(keys):
        raw=fetch(k); i=info(raw); i['bytes']=len(raw); i['sha']=k.split('/')[-1][:12]; vs.append(i)
    intact=[v for v in vs if v.get('intact')]
    fps={v.get('fp') for v in intact}
    rec_=dict(url=u, in_snapshot=u in dict(snap), in_receipt_pop=u in recset, n=len(vs), n_intact=len(intact), versions=[{k:v for k,v in x.items() if k!='text'} for x in vs])
    if len(intact)>=2:
        rec_['same_fp']=len(fps)==1 and None not in fps
        if not rec_['same_fp'] and intact[0]['fmt']=='pdf' and intact[0].get('text') and intact[1].get('text'):
            import difflib
            a,b=intact[0]['text'].split(),intact[1]['text'].split()
            sm=difflib.SequenceMatcher(None,a,b,autojunk=False)
            rec_['ratio']=round(sm.ratio(),4)
            rec_['ops']=[(t,' '.join(a[i1:i2])[:200],' '.join(b[j1:j2])[:200]) for t,i1,i2,j1,j2 in sm.get_opcodes() if t!='equal'][:8]
    out.append(rec_)
json.dump(out, open(O+'compare_bin.json','w'), indent=1)
C=collections.Counter((r['in_snapshot'], r['in_receipt_pop'], r['n_intact']>=2, r.get('same_fp')) for r in out)
for k,v in sorted(C.items(),key=str): print(k,v)
