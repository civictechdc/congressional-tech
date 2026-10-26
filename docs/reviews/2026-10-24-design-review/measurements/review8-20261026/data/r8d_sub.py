import gzip, json, os, collections
from multiprocessing import Pool
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
files=[os.path.join(d,f) for d,_,fs in os.walk(R) for f in fs if f.endswith('.gz')]
def work(p):
    c=collections.Counter(); ex={}
    with gzip.open(p,'rt') as fh:
        for line in fh:
            o=json.loads(line)
            for name in ('captures','file_references','download_state'):
                v=o.get(name)
                if isinstance(v,list):
                    for e in v[:3]:
                        k=(name,tuple(sorted(e.keys())) if isinstance(e,dict) else type(e).__name__)
                        c[k]+=1; ex.setdefault(k,json.dumps(e)[:600])
                elif v is not None:
                    k=(name,'TYPE',type(v).__name__); c[k]+=1; ex.setdefault(k,json.dumps(v)[:400])
    return c,ex
if __name__=='__main__':
    tot=collections.Counter(); ex={}
    with Pool(8) as pool:
        for c,e in pool.imap_unordered(work,files,chunksize=4):
            tot.update(c)
            for k,v in e.items(): ex.setdefault(k,v)
    for k,n in tot.most_common(30): print(n,k,'\n   ',ex[k][:600])
