import gzip,json,glob,collections as C
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/documents/'
c=C.Counter()
for p in sorted(glob.glob(R+'*/*.gz')):
    d=p.split('documents/')[1].split('/')[0]
    with gzip.open(p,'rt') as f:
        for l in f:
            if '"retained_import"' not in l: continue
            o=json.loads(l); r=o['record']
            if r.get('mode')!='retained_import': continue
            re_=r['recovery_evidence']; sa=r['source_associations'][0]
            if re_.get('match_basis'): c[('match_basis==sa.basis', re_['match_basis']==sa['basis'])]+=1
            if re_.get('imported_at'): c[('imported_at date == key date', re_['imported_at'][:10]==d)]+=1
            else: c[('no imported_at; key dir', 'undated' if d=='undated' else 'dated')]+=1
for k,v in sorted(c.items(),key=str): print(v,k)
