import gzip,json,glob,collections as C,re
from urllib.parse import urlsplit
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/documents/'
c=C.Counter(); ex={}
for p in sorted(glob.glob(R+'*/*.gz')):
    with gzip.open(p,'rt') as f:
        for l in f:
            if '"retained_import"' not in l: continue
            o=json.loads(l); r=o['record']
            if r.get('mode')!='retained_import': continue
            ou=r['source_associations'][0]['original_url']; u=r.get('url'); basis=r['source_associations'][0]['basis']
            if u==ou: k=('same',basis)
            else:
                a,b=urlsplit(u),urlsplit(ou)
                k=('wayback' if 'archive.org' in a.netloc else ('samehost' if a.netloc.lower().removeprefix('www.')==b.netloc.lower().removeprefix('www.') else 'otherhost'), basis)
            c[k]+=1
            if k not in ex: ex[k]=(re.sub(r'\?.*','?…',u)[:110], re.sub(r'\?.*','?…',ou)[:110])
            caps=o['captures']; c[('ncaps',len(caps))]+=1
            for e in caps: c[('cap.context_url==url', e.get('context_url')==u)]+=1
for k,v in sorted(c.items(),key=str): print(v,k)
for k,v in ex.items(): print(k,v)
