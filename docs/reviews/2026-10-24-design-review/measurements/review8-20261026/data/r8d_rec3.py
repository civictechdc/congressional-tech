import gzip, json, os, collections
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/documents'
c=collections.Counter()
for d,_,fs in os.walk(R):
    for f in fs:
        with gzip.open(os.path.join(d,f),'rt') as fh:
            for line in fh:
                if '"retained_import"' not in line: continue
                o=json.loads(line); rec=o.get('record')
                if not isinstance(rec,dict) or rec.get('mode')!='retained_import': continue
                re_=rec['recovery_evidence']; a=re_.get('acquisition') or {}
                if re_.get('original_url'): continue
                sa=[x.get('original_url') for x in rec.get('source_associations') or [] if isinstance(x,dict)]
                c['acq.original_url' if a.get('original_url') else 'no_acq']+=1
                c['source_assoc' if any(sa) else 'no_sa']+=1
                c['eq' if a.get('original_url') and a.get('original_url') in sa else 'neq']+=1
                c['mb:'+str(re_.get('match_basis'))]+=1
                c['ra:'+str(bool(rec.get('retrieved_at')))]+=1
print(c)
