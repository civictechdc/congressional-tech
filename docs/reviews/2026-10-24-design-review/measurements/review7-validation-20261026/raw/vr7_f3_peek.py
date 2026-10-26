"""Print the time-bearing fields (names and timestamp values only) of sample lines per shape."""
import gzip, json, sys, re
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
TS=re.compile(r'^\d{4}-\d\d-\d\d')
def tsfields(o, path='', out=None, depth=0):
    if out is None: out={}
    if depth>4: return out
    if isinstance(o, dict):
        for k,v in o.items():
            if k in ('content','body','cue_text','links','provider_response','provider_metadata'): continue
            p=path+'.'+str(k)
            if isinstance(v,str) and TS.match(v) and len(v)<40: out[p]=v
            elif isinstance(v,(dict,list)): tsfields(v,p,out,depth+1)
    elif isinstance(o,list):
        for i,v in enumerate(o[:2]): tsfields(v,path+f'[{i}]',out,depth+1)
    return out
for rk,n,skip in [('senate/captions/2026-09-29/assemble-20260930.jsonl.gz',3,1000),
             ('senate/captions/2026-09-28/assemble-20260930.jsonl.gz',2,10),
             ('documents/2026-10-05/download-20261005T212738Z-f3c0ed43a983-000007.jsonl.gz',3,0),
             ('house/pages/2026-10-02/download-20261002T222605Z-e64d8e807607-000036.jsonl.gz',2,0),
             ('documents/2026-09-29/assemble-20260930.jsonl.gz',3,500),
             ('govinfo/mods/2026-09-23/assemble-20260930.jsonl.gz',2,0),
             ('youtube/api/2026-09-29/assemble-20260930.jsonl.gz',2,5),
             ('senate/players/2026-09-29/assemble-20260930.jsonl.gz',2,5),
             ('congress/meetings/undated/assemble-20260930.jsonl.gz',2,5),
             ('documents/undated/assemble-20260930.jsonl.gz',2,1000)]:
    with gzip.open(R+rk,'rb') as fh:
        for i,raw in enumerate(fh):
            if i<skip: continue
            if i>=skip+n: break
            d=json.loads(raw)
            print(rk.split('/')[0:2], i+1, json.dumps(tsfields(d))[:900])
            hs=(d.get('record') or {}).get('response_headers') if isinstance(d.get('record'),dict) else None
            if isinstance(hs,dict): print('   hdr names', sorted(hs)[:20], 'date=', hs.get('date') or hs.get('Date'))
