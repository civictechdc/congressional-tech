import duckdb
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/filenames.parquet'
con=duckdb.connect(); con.execute("SET threads=4; SET memory_limit='8GB'")
q=lambda s: con.execute(s).fetchall()
t=f"read_parquet('{A}')"
print(q(f"select count(*), count(distinct body_key), count(distinct (filename, coalesce(source_url,''))), count(*) filter (where source_url is null), count(*) filter (where body_key is null) from {t}"))
print(q(f"select filename_origins, count(*) from {t} group by 1 order by 2 desc limit 10"))
print(q(f"select count(*) filter (where len(document_kind)>0), count(*) filter (where len(committee_code)>0), count(*) filter (where len(congress)>0), count(*) filter (where len(document_kind)>1) from {t}"))
