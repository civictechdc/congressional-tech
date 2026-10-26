import gzip, os, re, collections, json, time
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
fmt=re.compile(rb'"format": ?"([A-Za-z0-9_./+-]+)"')
keys=[b'"format"', b'"usable"', b'"body_complete"', b'"sniffed_format"', b'"complete"', b'"content_type"', b'"committeeMeeting"', b'"witnesses"', b'"links"']
cnt=collections.Counter(); fam=collections.Counter(); fv=collections.Counter(); lines=0; t=time.time(); ub=0
for d,_,fs in os.walk(R):
    for f in fs:
        p=os.path.join(d,f); family=os.path.relpath(p,R).split('/')[0]
        with gzip.open(p,'rb') as g:
            for line in g:
                lines+=1; ub+=len(line)
                for k in keys:
                    if k in line: cnt[(family,k.decode())]+=1
                if b'"format"' in line:
                    for m in set(fmt.findall(line)): fv[m.decode()]+=1
print('lines',lines,'uncompressed GB',ub/1e9,'secs',time.time()-t)
for k,v in sorted(cnt.items()): print(k,v)
print(fv.most_common(30))
