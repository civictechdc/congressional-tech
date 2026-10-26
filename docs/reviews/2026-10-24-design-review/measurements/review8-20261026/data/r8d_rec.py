import gzip, json, os, collections
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/documents'
paths=collections.Counter(); mb=collections.Counter(); nocat_paths=collections.Counter(); n=0
def walk(o,pre=''):
    if isinstance(o,dict):
        for k,v in o.items():
            yield pre+'.'+k, v
            yield from walk(v,pre+'.'+k)
for d,_,fs in os.walk(R):
    for f in fs:
        with gzip.open(os.path.join(d,f),'rt') as fh:
            for line in fh:
                if '"retained_import"' not in line: continue
                o=json.loads(line); rec=o.get('record')
                if not isinstance(rec,dict) or rec.get('mode')!='retained_import': continue
                n+=1
                ks=set(p for p,_ in walk(rec.get('recovery_evidence') or {},'re'))
                cat=[p for p in ks if 'categor' in p]
                for p in cat: paths[p]+=1
                if not any(p=='re.acquisition.prior_access_category' for p in ks):
                    for p in ks:
                        if p.count('.')<=2: nocat_paths[p]+=1
                mb[rec['recovery_evidence'].get('match_basis')]+=1
print(n); print(paths.most_common()); print(mb.most_common()); print(nocat_paths.most_common(40))
