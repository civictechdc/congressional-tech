import gzip,json,sys
def shape(v,d=0):
    if isinstance(v,dict): return {k:shape(x,d+1) for k,x in list(v.items())[:40]} if d<3 else 'obj'
    if isinstance(v,list): return ['list',len(v), shape(v[0],d+1) if v else None]
    return type(v).__name__
p=sys.argv[1]
with gzip.open(p,'rb') as f:
    for i,raw in enumerate(f):
        r=json.loads(raw); rec=r.get('record')
        tag='LIST' if isinstance(rec,list) else 'obj'
        if i<1 or tag=='LIST' or (isinstance(rec,dict) and rec.get('http_status')==''):
            print(i,len(raw),tag,json.dumps(shape(r))[:1500])
