"""Base: each prior attempt's own complete flag and status from the raw receipts (DM 6.1: an attempt's own completeness where the line
records it). Writes vm7_prior.parquet (receipt_key, receipt_line 1-based, attempt index 0-based, complete, http_status, error)."""
import duckdb, gzip, json, os, pyarrow as pa, pyarrow.parquet as pq
D=os.path.dirname(os.path.abspath(__file__))
B='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
M='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/'
want={}
for rk, rl in duckdb.sql(f"SELECT DISTINCT receipt_key, receipt_line FROM read_parquet('{B}captures.parquet') WHERE pointer_json LIKE '%prior_attempts%'").fetchall():
    want.setdefault(rk,set()).add(rl)
out=[]; missing=0
for rk, lines in want.items():
    if not os.path.exists(M+rk): missing+=1; continue
    with gzip.open(M+rk,'rt') as fh:
        for i,ln in enumerate(fh,1):
            if i not in lines: continue
            rec=json.loads(ln).get('record') or {}
            for j,a in enumerate(rec.get('prior_attempts') or []):
                out.append((rk,i,j,a.get('complete'),a.get('http_status'),str(a.get('error'))))
pq.write_table(pa.table({'receipt_key':[x[0] for x in out],'receipt_line':[x[1] for x in out],'attempt':[x[2] for x in out],
  'complete':[x[3] for x in out],'http_status':[x[4] for x in out],'error':[x[5] for x in out]}), D+'/vm7_prior.parquet')
print('receipts', len(want), 'missing', missing, 'attempts', len(out))
print(duckdb.sql(f"SELECT complete, error, count(*) FROM '{D}/vm7_prior.parquet' GROUP BY ALL ORDER BY 3 DESC LIMIT 12").fetchall())
