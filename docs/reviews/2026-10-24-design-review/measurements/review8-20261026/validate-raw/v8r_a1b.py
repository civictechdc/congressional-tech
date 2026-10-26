import gzip, json, glob, hashlib, collections as C, re
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/congress/meetings/'
full=C.defaultdict(set); ordered=C.defaultdict(set); raw=C.defaultdict(set); upd=C.defaultdict(set)
floats=0; rt=[]; started=[]; wrapped=[]
def hasfloat(v):
    if isinstance(v,float): return True
    if isinstance(v,dict): return any(hasfloat(x) for x in v.values())
    if isinstance(v,list): return any(hasfloat(x) for x in v)
    return False
for p in sorted(glob.glob(R+'*/*.gz')):
    fn=p.split('meetings/')[1]
    for i,l in enumerate(gzip.open(p,'rt')):
        o=json.loads(l); r=o['record']
        if 'meeting' in r: wrapped.append((fn,i,sorted(r.keys()), sorted(r['meeting'].keys())[:8] if isinstance(r['meeting'],dict) else type(r['meeting']).__name__)); 
        if 'eventId' not in r: continue
        k=(r['chamber'],r['eventId'])
        full[k].add(hashlib.sha256(json.dumps(r,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest())
        ordered[k].add(hashlib.sha256(json.dumps(r,ensure_ascii=False,separators=(',',':')).encode()).hexdigest())
        m=re.search(r'"record":(\{.*\}),"captures"',l)
        raw[k].add(hashlib.sha256(m.group(1).encode()).hexdigest() if m else None)
        upd[k].add(r.get('updateDate'))
        floats+=hasfloat(r)
        if '_retrieved_at' in r: rt.append((fn,i,k))
        if 'started_at' in r: started.append((fn,i,k,r.get('retrieved_at') is not None))
dist=lambda d: C.Counter(len(v) for v in d.values())
print('keys',len(full)); print('versions per key sorted-canonical',dist(full)); print('insertion-order canonical',dist(ordered)); print('raw substring',dist(raw)); print('updateDate per key',dist(upd))
print('records with floats',floats)
print('_retrieved_at lines',len(rt),C.Counter(x[0] for x in rt)); print('started_at lines',len(started),C.Counter((x[0],x[3]) for x in started))
print('wrapped',len(wrapped),wrapped[:2])
# does each multi-version key differ only by updateDate ordering? check 2026-09-30 records newer
