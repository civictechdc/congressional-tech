import gzip,json,glob,collections as C,re,time
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
FETCH=('captured_at','observed_at','_retrieved_at','started_at','checked_at','capture_date','raw_acquired_at','finished_at','recorded_at','parent_retrieved_at','detail_retrieved_at','inspected_at','completed_at','created_at','reported_retrieved_at')
NONFETCH=('date','updateDate','upload_date','release_date','release_timestamp','timestamp','prior_observed_at','reclassified_at')
c=C.Counter(); t0=time.time()
for p in sorted(glob.glob(R+'**/*.gz',recursive=True)):
    key=p.replace(R,''); fam='/'.join(key.split('/')[:-2]); sub=fam+('/undated' if '/undated/' in key else '')
    with gzip.open(p,'rt') as f:
        for l in f:
            o=json.loads(l); r=o.get('record'); r=r if isinstance(r,dict) else ({} if not isinstance(r,list) or not r or not isinstance(r[0],dict) else r[0])
            m=r.get('meeting') if isinstance(r.get('meeting'),dict) else {}
            rows=(o.get('captures') or []) or (o.get('file_references') or []) or [None]
            for e in rows:
                e=e if isinstance(e,dict) else {}
                if e.get('retrieved_at') or o.get('retrieved_at') or r.get('retrieved_at'): continue
                c[('norowtime',)]+=1
                found=None
                for k in FETCH:
                    if e.get(k) or r.get(k) or o.get(k) or m.get(k): found=k; break
                if found: c[('first fetch-time key',found)]+=1; c[('fam',sub,found)]+=1
                else:
                    nf=[k for k in NONFETCH if r.get(k)]
                    c[('no fetch-time; content-date only' if nf else 'no time at all',)]+=1; c[('fam',sub,'none' if not nf else 'content-date-only')]+=1
print(time.time()-t0)
for k,v in sorted(c.items(),key=lambda x:(-x[1])): 
    if v>50: print(v,k)
