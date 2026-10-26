import duckdb
con=duckdb.connect(); con.execute("SET threads=4")
C='/Users/mikewolfd/Work/congressional-tech/.cache/nara-filename-estimate-20261015/publication-all-20261015/'
q=lambda s: con.execute(s).fetchall()
print(q(f"select resolution, count(*) from read_parquet('{C}new-captures.parquet') group by 1 order by 2 desc limit 15"))
print(q(f"select outcome, count(*), count(distinct sha256) from read_parquet('{C}new-download-state.parquet') group by 1 order by 2 desc limit 20"))
print(q(f"describe select * from read_parquet('{C}new-download-state.parquet')"))
