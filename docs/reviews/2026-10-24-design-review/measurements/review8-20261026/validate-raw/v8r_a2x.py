import gzip,json,glob,collections as C
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/documents/'
c=C.Counter()
for p in sorted(glob.glob(R+'*/*.gz')):
    with gzip.open(p,'rt') as f:
        for l in f:
            if '"retained_import"' not in l: continue
            o=json.loads(l); r=o['record']
            if r.get('mode')!='retained_import': continue
            re_=r['recovery_evidence']; acq=re_.get('acquisition') or {}
            c[(r['source_associations'][0]['basis'], acq.get('prior_access_category') or '-', 'pubreq' if r.get('publisher_requested') else '', 'imported_at' if re_.get('imported_at') else 'no-imported_at')]+=1
for k,v in sorted(c.items()): print(v,k)
