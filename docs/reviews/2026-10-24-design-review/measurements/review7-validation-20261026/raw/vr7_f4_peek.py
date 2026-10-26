"""Structure of senate/captions/undated lines that carry many captures (names/types only, long strings cut)."""
import gzip, json, collections
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
def shape(o, depth=0):
    if depth>5: return '...'
    if isinstance(o,dict): return {k:shape(v,depth+1) for k,v in list(o.items())[:25]}
    if isinstance(o,list): return [shape(o[0],depth+1), f'x{len(o)}'] if o else []
    if isinstance(o,str): return 'str' if not o[:4].isdigit() else o[:32]
    return type(o).__name__
seen=collections.Counter()
with gzip.open(R+'senate/captions/undated/assemble-20260930.jsonl.gz','rb') as fh:
    for i,raw in enumerate(fh):
        d=json.loads(raw); n=len(d['captures'])
        if n>100 and seen['big']<1:
            seen['big']+=1
            print('line',i+1,'caps',n); print(json.dumps(shape(d['record']))[:2500]); print('cap0',json.dumps(d['captures'][0])[:600])
