import gzip, os, re, collections, time
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
pat={'links_nonempty':re.compile(rb'"links": ?\[\{'), 'links_group':re.compile(rb'"group_path"'), 'links_basis_senate':re.compile(rb'"basis": ?"senate_document"'),
     'mode_retained':re.compile(rb'"mode": ?"retained_import"'), 'witnesses_nonempty':re.compile(rb'"witnesses": ?\[\{'), 'content_disposition':re.compile(rb'content-disposition', re.I)}
cnt=collections.Counter(); t=time.time()
for d,_,fs in os.walk(R):
    for f in fs:
        p=os.path.join(d,f); fam='/'.join(os.path.relpath(p,R).split('/')[:2])
        if re.match(r'documents/\d', fam): fam='documents/dated'
        with gzip.open(p,'rb') as g:
            for line in g:
                cnt[(fam,'lines')]+=1
                for k,r in pat.items():
                    if r.search(line): cnt[(fam,k)]+=1
print('secs',time.time()-t)
for k,v in sorted(cnt.items()): print(k,v)
