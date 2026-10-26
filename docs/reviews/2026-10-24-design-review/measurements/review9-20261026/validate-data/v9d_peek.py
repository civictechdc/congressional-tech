import gzip, json, sys, glob, re, collections
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
def shape(o, d=0):
    if isinstance(o, dict):
        return {k: shape(v, d+1) for k, v in list(o.items())[:40]} if d < 3 else '{..}'
    if isinstance(o, list):
        return [shape(o[0], d+1)] if o else []
    if isinstance(o, str):
        return 'str' if not o.startswith('/') else 'ABS'
    return type(o).__name__
for f in sys.argv[1:]:
    with gzip.open(f,'rt') as fh:
        l = json.loads(fh.readline())
    print(f.replace(R,''), json.dumps(shape(l))[:3000])
