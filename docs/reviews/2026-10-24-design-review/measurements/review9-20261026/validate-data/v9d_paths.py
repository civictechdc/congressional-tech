import gzip, json, os, re, collections
from multiprocessing import Pool
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
PFX=['/Users/','/home/','/private/','/tmp/','/var/folders/','/var/','/Volumes/','/opt/','/root/','/runner/','/github/','/mnt/']
NEEDLE=[p.encode() for p in PFX]
ANY=re.compile('(' + '|'.join(re.escape(p) for p in PFX) + ')')
import time
def scan(fp):
    t0=time.time()
    out=collections.Counter(); ex=collections.defaultdict(list); lines=collections.defaultdict(set)
    with gzip.open(fp,'rb') as fh:
        for ln, raw in enumerate(fh):
            if not any(n in raw for n in NEEDLE): continue
            obj=json.loads(raw)
            def walk(o,p,iskey=False):
                if isinstance(o,dict):
                    for k,v in o.items():
                        walk(k,p+'.{key}',True); walk(v,p+'.'+('<k>' if ('/' in k or len(k)>40) else k))
                elif isinstance(o,list):
                    for x in o: walk(x,p+'[]')
                elif isinstance(o,str):
                    for m in ANY.finditer(o):
                        pre=o[max(0,m.start()-1):m.start()]
                        whole = m.start()==0
                        url_ctx = (not whole) and ('://' in re.split(r'[\s"]', o[max(0,m.start()-300):m.start()])[-1]) or (pre and (pre.isalnum() or pre in '.-_%)'))
                        kind=('key' if iskey else 'value')+('_whole' if whole else ('_urlctx' if url_ctx else '_embedded'))
                        cat=m.group(1)
                        out[(cat,kind)]+=1; lines[(cat,kind)].add((fp,ln))
                        if kind.endswith('_embedded') and len(ex[(cat,kind)])<4:
                            ctx=o[max(0,m.start()-25):m.start()]
                            ctx=re.sub(r'[A-Za-z0-9]{6,}','<w>',ctx)
                            ex[(cat,kind)].append((p, ctx))
            walk(obj,'$')
    print(round(time.time()-t0,1), fp[len(R):], flush=True, file=open('out/timing.log','a'))
    return out, ex, {k:len(v) for k,v in lines.items()}, fp
def main():
    files=sorted(os.path.join(d,f) for d,_,fs in os.walk(R) for f in fs if f.endswith('.gz'))
    tot=collections.Counter(); exs=collections.defaultdict(list); L={}; recs=collections.defaultdict(set)
    with Pool(8) as p:
        for o,e,l,fp in p.imap_unordered(scan,files,chunksize=4):
            tot.update(o)
            for k,v in e.items(): exs[k]+=v
            for k,v in l.items(): L[k]=L.get(k,0)+v; recs[k].add(fp)
    L=dict(L) if False else L
    for k in sorted(tot): print(k, 'n=',tot[k],'lines=',L[k],'receipts=',len(recs[k]))
    print('--- embedded examples (redacted context; path itself omitted)')
    for k,v in exs.items():
        for p,c in v[:4]: print(k, p[:90], repr(c))

if __name__=='__main__':
    main()
