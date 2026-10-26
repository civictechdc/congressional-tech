import gzip, json, sys, re
def red(o):
    if isinstance(o, dict): return {k: red(v) for k, v in o.items() if k.lower()!='set-cookie'} | ({'set-cookie':'<R>'} if any(k.lower()=='set-cookie' for k in o) else {})
    if isinstance(o, list): return [red(x) for x in o[:3]]
    if isinstance(o, str):
        if re.match(r'^/(Users|home|private|tmp|var)/', o): return '<ABS>'
        return o[:60]
    return o
f=sys.argv[1]; want=sys.argv[2]
with gzip.open(f,'rt') as fh:
    for line in fh:
        if want in line:
            d=json.loads(line); print(json.dumps(red(d), indent=1)[:6000]); break
