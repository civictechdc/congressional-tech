import gzip, json, os, sys, collections
from multiprocessing import Pool
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
files=[os.path.join(d,f) for d,_,fs in os.walk(R) for f in fs if f.endswith('.gz')]
def work(p):
    c=collections.Counter(); ex={}
    with gzip.open(p,'rt') as fh:
        for line in fh:
            o=json.loads(line)
            top=tuple(sorted(o.keys()))
            rec=o.get('record')
            rk = ('LIST',) if isinstance(rec,list) else tuple(sorted(rec.keys())) if isinstance(rec,dict) else None
            k=(top,rk); c[k]+=1
            if k not in ex: ex[k]=p
    return c,ex
if __name__=='__main__':
    tot=collections.Counter(); ex={}
    with Pool(8) as pool:
        for c,e in pool.imap_unordered(work,files,chunksize=4):
            tot.update(c)
            for k,v in e.items(): ex.setdefault(k,v)
    print('lines',sum(tot.values()),'files',len(files),'shapes',len(tot))
    tops=collections.Counter()
    for (t,r),n in tot.items(): tops[t]+=n
    for t,n in tops.most_common(): print(n,t)
    rkc=collections.Counter()
    for (t,r),n in tot.items():
        for k in (r or ()): rkc[k]+=n
    print(rkc.most_common())
