import duckdb, time, sys
S='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review8/data'
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
con=duckdb.connect(S+'/r8d.duckdb')
con.execute("SET threads=8; SET memory_limit='12GB'")
t=time.time()
con.execute(f"""CREATE OR REPLACE TABLE lines AS
SELECT filename AS f, row_number() OVER (PARTITION BY filename) AS ln, json AS j
FROM read_ndjson_objects('{R}/**/*.jsonl.gz', filename=true, maximum_object_size=1000000000)""")
print(time.time()-t, con.execute("select count(*), count(distinct f) from lines").fetchall())
