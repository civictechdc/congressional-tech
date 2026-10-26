import gzip, json, os, collections
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/documents'
c=collections.Counter(); kinds=collections.Counter(); cats=collections.Counter(); imp=collections.Counter()
for d,_,fs in os.walk(R):
    for f in fs:
        with gzip.open(os.path.join(d,f),'rt') as fh:
            for line in fh:
                if '"retained_import"' not in line: continue
                o=json.loads(line); rec=o.get('record')
                if not isinstance(rec,dict) or rec.get('mode')!='retained_import': continue
                re_=rec['recovery_evidence']; a=re_.get('acquisition') or {}
                c['has_re_original_url' if re_.get('original_url') else 'no_re_original_url']+=1
                c['has_imported_at' if re_.get('imported_at') else 'no_imported_at']+=1
                c['has_pac' if a.get('prior_access_category') else ('has_acq_category' if a.get('category') else ('has_acq_kind' if a.get('kind') else 'none'))]+=1
                if not a.get('prior_access_category'):
                    kinds[a.get('kind')]+=1; cats[a.get('category')]+=1
                c['has_body_path' if a.get('body_path') else 'no_body_path']+=1
print(c); print(kinds.most_common(20)); print(cats.most_common(20))
