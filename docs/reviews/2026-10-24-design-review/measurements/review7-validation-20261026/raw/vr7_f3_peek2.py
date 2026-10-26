"""Show the structure of a Senate caption assemble line with captured_at (long strings truncated; no header values)."""
import gzip, json
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
def trunc(o):
    if isinstance(o,dict): return {k:trunc(v) for k,v in o.items() if k not in ('cookie','set-cookie','authorization')}
    if isinstance(o,list): return [trunc(x) for x in o[:3]]+(['...%d more'%(len(o)-3)] if len(o)>3 else [])
    if isinstance(o,str) and len(o)>120: return o[:120]+'...'
    return o
with gzip.open(R+'senate/captions/2026-09-29/assemble-20260930.jsonl.gz','rb') as fh:
    for i,raw in enumerate(fh):
        d=json.loads(raw)
        if 'captured_at' in d['record']:
            print(json.dumps(trunc(d),indent=1)[:5000]); break
