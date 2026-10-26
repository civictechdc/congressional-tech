import duckdb
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs'
c=duckdb.connect('../validate-data/out/v9d.duckdb', read_only=True); q=lambda s:c.sql(s).fetchall()
cols=[r[0] for r in duckdb.sql(f"describe select * from read_parquet('{A}/readings/*.parquet', union_by_name=true)").fetchall()]
print('content cols', [x for x in cols if x.startswith('content')])
c.sql(f"""create temp table leg2 as select regexp_extract(body_key,'([0-9a-f]{{64}})',1) sh,
  bool_or(status='completed' and body_format[1]='pdf' and coalesce(len(content_document_kind),0)>0) opened
  from read_parquet('{A}/readings/*.parquet', union_by_name=true) group by 1""")
c.sql("create temp table p2 as select pdf.*, coalesce(opened,false) o from pdf left join leg2 using(sh)")
def dist(cond,label):
    r=q(f"select count(*), round(sum(bytes)/1e9,2), round(sum(sbytes)/1e9,2), round(median(bytes)/1e6,3), round(100.0*avg((bytes>10e6)::int),1) from p2 where {cond}")[0]
    print(f'{label:52s} n={r[0]} contentGB={r[1]} storedGB={r[2]} medianMB={r[3]} pct>10MB={r[4]}')
dist('true','all PDFs')
dist('a','capture-checked (A)')
dist('not a and l','legacy-only (plan borrows)')
dist('not a and l and o','legacy-only, opened proven (content_document_kind)')
dist('not a and l and not o','legacy-only, format-only (no proof of open)')
dist('not (a or l)','unchecked today')
dist('not (a or o)','unchecked under strict selector')
dist("not (a or o) and coalesce(fmt,'')<>'html'",'unchecked strict, excl legacy-html')
