"""documents/undated and congress/meetings/undated: nested keys (paths with type counts) to find any time/status fields."""
import json, glob, collections
for rk in ('documents/undated/assemble-20260930.jsonl.gz','congress/meetings/undated/assemble-20260930.jsonl.gz'):
    for fn in glob.glob('scan/types/*.json'):
        d=json.load(open(fn))
        if d['rk']!=rk: continue
        rows=[(p,t,n,nl) for p,t,n,nl in d['types'] if any(k in p.split('.')[-1].lower() for k in ('_at','time','date','status','retriev','fetch','url','outcome'))]
        print('##',rk)
        for p,t,n,nl in sorted(rows,key=lambda x:-x[3])[:30]: print('  ',p,t,'values',n,'lines',nl)
