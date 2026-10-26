import gzip,json,glob,collections as C
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
c=C.Counter(); body=C.Counter()
ALT=('_url','final_url','resolved_url','master_url','segment_url','playlist_url','source_url')
for p in sorted(glob.glob(R+'**/*.gz',recursive=True)):
    key=p.replace(R,''); fam='/'.join(key.split('/')[:-2])
    with gzip.open(p,'rt') as f:
        for l in f:
            o=json.loads(l); r=o.get('record'); r=r if isinstance(r,dict) else {}
            if o.get('url') or o.get('requested_url') or r.get('url') or r.get('requested_url'): continue
            if any(r.get(k) for k in ALT): continue
            rows=(o.get('captures') or []) or (o.get('file_references') or [])
            ctx=any(isinstance(e,dict) and e.get('context_url') for e in rows)
            sig=','.join(sorted(r.keys()))[:70]
            c[(fam, 'ctx' if ctx else 'noctx', sig)]+=1
            body['lines with body' if any(isinstance(e,dict) and e.get('sha256') for e in rows) else 'bodiless']+=1
print(sum(c.values()), body)
for k,v in c.most_common(12): print(v,k)
