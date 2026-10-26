import gzip,json,glob,collections as C
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
c=C.Counter(); pac=C.Counter(); cat=C.Counter(); kind=C.Counter(); mb=C.Counter(); sab=C.Counter(); combo=C.Counter(); a8=C.Counter(); fams=C.Counter(); sa_len=C.Counter()
for p in sorted(glob.glob(R+'**/*.gz',recursive=True)):
    with gzip.open(p,'rt') as f:
        for l in f:
            if '"retained_import"' not in l: continue
            o=json.loads(l); r=o.get('record')
            if not isinstance(r,dict) or r.get('mode')!='retained_import': continue
            fams[p.split('receipts/')[1].split('/')[0]]+=1
            caps=o.get('captures') or []; frs=o.get('file_references') or []
            c[('captures_nonempty',bool(caps)),('fr_nonempty',bool(frs))]+=1
            re_=r.get('recovery_evidence') or {}; acq=re_.get('acquisition') or {}; rep=re_.get('representation') if isinstance(re_.get('representation'),dict) else {}; c[('representation type',type(re_.get('representation')).__name__)]+=1
            sa=r.get('source_associations') or []; sa_len[len(sa)]+=1
            sa_ou={x.get('original_url') for x in sa if x.get('original_url')}
            for x in sa: sab[x.get('basis')]+=1
            pac[acq.get('prior_access_category')]+=1; cat[acq.get('category') or rep.get('category')]+=1; kind[acq.get('kind') or rep.get('kind')]+=1
            mb[re_.get('match_basis')]+=1
            src=tuple(int(bool(v)) for v in (re_.get('original_url'),acq.get('original_url'),rep.get('original_url'),sa_ou))
            combo[src]+=1
            ous={v for v in (re_.get('original_url'),acq.get('original_url'),rep.get('original_url')) if v}|sa_ou
            c[('distinct original urls across sources',len(ous))]+=1
            u=r.get('url'); rec=acq.get('recovered_url') or rep.get('recovered_url')
            ou=re_.get('original_url') or (sorted(sa_ou)[0] if sa_ou else None)
            a8[('url==recovered_url',u==rec,'url==original_url',u==ou,'recovered==original',rec==ou)]+=1
            c[('imported_at',bool(re_.get('imported_at')),'retrieved_at',bool(r.get('retrieved_at')))]+=1
            c[('has acquisition',bool(acq),'has representation',bool(rep))]+=1
for k,v in sorted(c.items(),key=str): print(v,k)
print('families',fams); print('sa_len',sa_len)
print('pac',pac.most_common()); print('category',cat.most_common()); print('kind',kind.most_common()); print('re.match_basis',mb.most_common()); print('sa.basis',sab.most_common())
print('original_url presence (re,acq,rep,sa)',combo.most_common())
print('A8',a8.most_common())
