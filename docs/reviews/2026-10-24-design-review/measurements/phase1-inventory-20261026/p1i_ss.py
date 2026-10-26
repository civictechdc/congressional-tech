import duckdb
con=duckdb.connect(); con.execute("SET threads=4")
C='/Users/mikewolfd/Work/congressional-tech/.cache/nara-filename-estimate-20261015/publication-all-20261015/new-captures.parquet'
q=lambda s: con.execute(s).fetchall()
print(q(f"""with b as (select body_key, count(distinct stored_sha256) n, count(distinct stored_bytes) nb, count(distinct bytes) nr from read_parquet('{C}') where body_key is not null group by 1)
 select count(*) filter (where n>1), count(*) filter (where nb>1), count(*) filter (where nr>1), count(*) filter (where n=0) from b"""))
print(q(f"select count(*) from read_parquet('{C}') where body_key is not null and body_key not like '%'||sha256||'.gz'"))
