import gzip, json, os, re, collections
from multiprocessing import Pool
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
def scan(fp):
    names=collections.Counter(); vals=collections.Counter(); keys=collections.Counter()
    with gzip.open(fp,'rb') as fh:
        for raw in fh:
            if b'et-cookie' not in raw.lower(): continue
            def walk(o,p):
                if isinstance(o,dict):
                    for k,v in o.items():
                        if 'set-cookie' in k.lower() and k.lower()!='set-cookie': keys[k]+=1
                        if k in ('name','Name') and isinstance(v,str) and 'set-cookie' in v.lower() and v.strip().lower()!='set-cookie': names[v]+=1
                        walk(v,p+'.'+k)
                elif isinstance(o,list):
                    for x in o: walk(x,p+'[]')
                elif isinstance(o,str) and 'set-cookie' in o.lower() and not p.endswith('.name'):
                    i=o.lower().index('set-cookie'); vals[(p[-40:], re.sub(r'[^\s:,;=]{1,}', 'w', o[max(0,i-15):i+25]))]+=1
            walk(json.loads(raw),'$')
    return names, vals, keys
def main():
    files=sorted(os.path.join(d,f) for d,_,fs in os.walk(R) for f in fs if f.endswith('.gz'))
    N=collections.Counter(); V=collections.Counter(); K=collections.Counter()
    with Pool(8) as p:
        for n,v,k in p.imap_unordered(scan,files,chunksize=4): N.update(n); V.update(v); K.update(k)
    print('odd header names:', N.most_common(10)); print('odd keys:', K.most_common(10))
    for (p,ctx),n in V.most_common(25): print(n, p, repr(ctx))
if __name__=='__main__': main()
