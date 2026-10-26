import duckdb,sys
P='/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/review8/data/dl/'
con=duckdb.connect()
for n in ['congress_bills','cbo_cost_estimates','bill_vote_references','committee_assignments','committees','member_terms','members','nominations','roll_call_votes']:
    con.execute(f"create view {n} as select * from read_parquet('{P}{n}.parquet')")
for q in [x for x in sys.stdin.read().split(';;') if x.strip()]:
    res=con.execute(q); rows=res.fetchall()
    print('>>',q.strip()[:160].replace('\n',' ')); print([d[0] for d in res.description])
    for r in rows[:40]: print(r)
