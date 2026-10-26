import duckdb, pickle, pyarrow as pa, gzip, json, collections
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs'
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
c=duckdb.connect('out/v9d.duckdb')
M=pickle.load(open('out/stored.pkl','rb'))
miss=[sh for sh,v in M.items() if not [p for p in v[0] if p[0]!='None' and p[1] is not None]]
c.register('ms',pa.table({'sh':miss}))
for r in c.sql(f"select reference_kind, family, count(distinct sha256) from '{A}/captures.parquet' i join ms on ms.sh=i.sha256 group by all order by 3 desc limit 12").fetchall(): print(r)
print(c.sql(f"select count(distinct sha256) from '{A}/captures.parquet' i join ms on ms.sh=i.sha256").fetchall())
ex=c.sql(f"select receipt_key, receipt_line, sha256, stored_sha256 from '{A}/captures.parquet' i join ms on ms.sh=i.sha256 where receipt_key is not null limit 3").fetchall()
for rk,rl,sh,ss in ex:
    print('receipt', rk[:60], rl)
    p=R+'/'+rk.split('receipts/',1)[-1] if 'receipts/' in rk else None
    try:
        with gzip.open(p,'rb') as fh:
            for i,raw in enumerate(fh):
                if i==rl or (rl and i==rl-1):
                    s=raw.decode()
                    print('  line', i, 'content sha present', sh in s, 'stored sha present', ss in s)
    except Exception as e: print('  ', type(e).__name__)
