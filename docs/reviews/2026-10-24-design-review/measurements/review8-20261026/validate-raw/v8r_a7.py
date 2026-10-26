import gzip,json,glob,collections as C
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
c=C.Counter(); vals=C.Counter()
for p in sorted(glob.glob(R+'**/*.gz',recursive=True)):
    with gzip.open(p,'rt') as f:
        for l in f:
            if 'etry' not in l: continue
            o=json.loads(l); r=o.get('record'); r=r if isinstance(r,dict) else {}
            rl=r.get('retry_later'); ds=isinstance(rl,dict) and 'delay_seconds' in rl
            h=r.get('response_headers') or o.get('response_headers') or {}
            ra=None
            if isinstance(h,dict):
                for k,v in h.items():
                    if k.lower()=='retry-after': ra=v
            st=r.get('http_status') or r.get('status_code') or r.get('status')
            c[('delay_seconds',ds,'retry-after hdr',ra is not None,'status',st if st in (429,503) else 'other', 'outcome', r.get('outcome') if r.get('outcome') in ('retry_later',) else 'other')]+=1
            if ds and ra is not None: vals[('match' if str(rl['delay_seconds'])==str(ra).strip() else 'differ')]+=1
            if ds: vals[('reason',rl.get('reason'))]+=1
for k,v in sorted(c.items(),key=lambda x:-x[1]): print(v,k)
print(vals.most_common(8))
