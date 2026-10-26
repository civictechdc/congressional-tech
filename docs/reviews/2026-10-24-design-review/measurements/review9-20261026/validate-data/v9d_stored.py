import gzip, json, os, collections, pickle
from multiprocessing import Pool
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
def scan(fp):
    m={}
    with gzip.open(fp,'rb') as fh:
        for raw in fh:
            if b'stored_' not in raw and b'"sha256"' not in raw: continue
            d=json.loads(raw)
            for src in ('captures','file_references'):
                for e in d.get(src) or []:
                    if not isinstance(e,dict) or 'sha256' not in e: continue
                    k=(e.get('stored_sha256'), e.get('stored_bytes'))
                    s=m.setdefault(e['sha256'], [collections.Counter(), e.get('bytes'), (e.get('body_key') or '')[-3:]])
                    s[0][k]+=1
    return m
def main():
    files=sorted(os.path.join(d,f) for d,_,fs in os.walk(R) for f in fs if f.endswith('.gz'))
    M={}
    with Pool(8) as p:
        for m in p.imap_unordered(scan,files,chunksize=4):
            for sh,(c,b,suf) in m.items():
                if sh in M: M[sh][0].update(c)
                else: M[sh]=[c,b,suf]
    C=collections.Counter()
    for sh,(c,b,suf) in M.items():
        keys=set(c)
        good={k for k in keys if k[0] and k[1] is not None}
        C['bodies']+=1
        C['distinct_pairs=%d'%len(good) if len(good)<3 else 'distinct_pairs>=3']+=1
        if any(k[0] is None or k[1] is None for k in keys): C['some_entry_missing_stored']+=1
        if any(k[0]==sh for k in good): C['stored_sha_eq_content_sha']+=1
        if good:
            sb=next(iter(good))[1]
            if b is not None:
                C['stored_lt_bytes' if sb<b else ('stored_eq_bytes' if sb==b else 'stored_gt_bytes')]+=1
        C['body_key_suffix='+suf]+=1
    for k,v in sorted(C.items()): print(k,v)
    pickle.dump({sh:(sorted((str(a),b) for a,b in c), byt) for sh,(c,byt,suf) in M.items()}, open('out/stored.pkl','wb'))
if __name__=='__main__': main()
