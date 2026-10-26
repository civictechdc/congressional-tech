import gzip, json, sys
p=sys.argv[1]; n=int(sys.argv[2]) if len(sys.argv)>2 else 1
def shape(v, d=0):
    if isinstance(v, dict):
        return {k: shape(x, d+1) for k,x in v.items()} if d<4 else '{..}'
    if isinstance(v, list):
        return [shape(v[0], d+1), f'len={len(v)}'] if v else []
    if isinstance(v,str): return 'str:'+v[:60]
    return v
with gzip.open(p,'rt') as f:
    for i,l in enumerate(f):
        if i>=n: break
        print(json.dumps(shape(json.loads(l)), indent=1)[:6000])
