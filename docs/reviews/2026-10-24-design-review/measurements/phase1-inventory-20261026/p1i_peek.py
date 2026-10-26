import gzip, json, os, sys, collections
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/documents/'
for day in ('2026-10-01','2026-10-05','2026-10-12'):
    fs=sorted(os.listdir(R+day))
    names=collections.Counter(f.rsplit('-',1)[0] for f in fs)
    print(day, names.most_common(4))
    with gzip.open(R+day+'/'+fs[0]) as g:
        d=json.loads(g.readline())
    def shape(o,depth=0):
        if isinstance(o,dict): return {k:(shape(v,depth+1) if depth<2 and k not in ('response_headers','headers','response_header_items') else '...') for k,v in o.items()}
        if isinstance(o,list): return [shape(o[0],depth+1)] if o else []
        return type(o).__name__
    print(json.dumps(shape(d))[:1500])
    rec=d.get('record',{}); ds=d.get('download_state',{})
    print('outcome', rec.get('outcome'), ds.get('outcome'), 'format', rec.get('format'), ds.get('format'), 'usable', rec.get('usable'), ds.get('usable'))
