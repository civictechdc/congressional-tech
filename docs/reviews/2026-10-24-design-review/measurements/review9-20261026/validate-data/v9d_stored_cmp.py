import duckdb, pickle, pyarrow as pa
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs'
c=duckdb.connect('out/v9d.duckdb')
print('index', c.sql(f"""select count(*) bodies, count(*) filter (where nss=1 and nsb=1) one_each, count(*) filter (where nss=0 or nsb=0) no_val, count(*) filter (where eq) eq_content, count(*) filter(where nullrows>0) any_null_row
 from (select sha256, count(distinct stored_sha256) nss, count(distinct stored_bytes) nsb, bool_or(stored_sha256=sha256) eq, count(*) filter (where stored_sha256 is null) nullrows from '{A}/captures.parquet' group by 1)""").fetchall())
M=pickle.load(open('out/stored.pkl','rb'))
rows=[(sh, len([p for p in v[0] if p[0]!='None' and p[1] is not None])) for sh,v in M.items()]
c.register('rs',pa.table({'sh':[r[0] for r in rows],'npairs':[r[1] for r in rows]}))
for r in c.sql(f"""select rs.npairs=0 as receipts_missing, i.reference_kind, i.family, count(distinct i.sha256) from '{A}/captures.parquet' i join rs on rs.sh=i.sha256 group by all order by 1,4 desc limit 24""").fetchall(): print(r)
pairs=[(sh,p[0],p[1]) for sh,v in M.items() for p in v[0] if p[0]!='None' and p[1] is not None]
c.register('rp',pa.table({'sh':[p[0] for p in pairs],'ss':[p[1] for p in pairs],'sb':[p[2] for p in pairs]}))
print('agree', c.sql(f"""select count(*), count(*) filter (where i.stored_sha256=rp.ss and i.stored_bytes=rp.sb) from rp join (select distinct sha256, stored_sha256, stored_bytes from '{A}/captures.parquet') i on i.sha256=rp.sh""").fetchall())
