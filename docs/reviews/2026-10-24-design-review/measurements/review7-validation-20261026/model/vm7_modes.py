"""Base: receipt lines whose record.mode is not 'fetch' (recovery imports), from the raw mirror. Writes vm7_modes.parquet (receipt_key, receipt_line 1-based, mode)."""
import os, gzip, json, collections, pyarrow as pa, pyarrow.parquet as pq
M='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/'
out=[]; cnt=collections.Counter()
for r,d,fs in os.walk(M+'receipts'):
    for f in fs:
        p=os.path.join(r,f); k=p[len(M):]
        with gzip.open(p,'rt') as fh:
            for i,ln in enumerate(fh,1):
                if '"mode"' not in ln: cnt['nomode']+=1; continue
                o=json.loads(ln); rec=o.get('record') or {}
                m=rec.get('mode') or o.get('mode')
                cnt[str(m)]+=1
                if m not in ('fetch',None): out.append((k,i,str(m)))
print(cnt)
pq.write_table(pa.table({'receipt_key':[x[0] for x in out],'receipt_line':[x[1] for x in out],'mode':[x[2] for x in out]}), os.path.dirname(os.path.abspath(__file__))+'/vm7_modes.parquet')
print(len(out))
