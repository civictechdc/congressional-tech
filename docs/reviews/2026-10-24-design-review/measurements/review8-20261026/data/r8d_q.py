import duckdb, sys, time
S='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review8/data'
con=duckdb.connect(S+'/r8d.duckdb')
con.execute("SET threads=8; SET memory_limit='10GB'")
con.execute(f"CREATE OR REPLACE VIEW r AS SELECT * FROM read_parquet('{S}/rows/*.parquet')")
I='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes'
for n in ['captures','documents','document-filenames','download-state']:
    con.execute(f"CREATE OR REPLACE VIEW \"{n}\" AS SELECT * FROM read_parquet('{I}/{n}.parquet')")
sql=sys.stdin.read()
for q in [x for x in sql.split(';;') if x.strip()]:
    t=time.time()
    res=con.execute(q)
    rows=res.fetchall(); cols=[d[0] for d in res.description]
    print('>>',q.strip()[:200].replace('\n',' '))
    print(cols)
    for row in rows[:60]: print(row)
    print(f'({len(rows)} rows, {time.time()-t:.1f}s)')
