import duckdb
con=duckdb.connect()
I='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/'
q=f"""
with u as (select context_url url from '{I}captures.parquet' union all select url from '{I}download-state.parquet' union all select source_url from '{I}documents.parquet'),
p as (select distinct regexp_extract(url,'CHRG-(\\d+)([hsj])hrg(\\d+)',0) pkg, regexp_extract(url,'CHRG-(\\d+)([hsj])hrg(\\d+)',3) j from u where regexp_matches(url,'CHRG-\\d+[hsj]hrg\\d+'))
select count(*) pkgs, count(*) filter (where j like '0%') leading0, list(pkg) filter (where j like '0%'), min(length(j)), max(length(j)) from p
"""
print(con.sql(q).fetchall())
