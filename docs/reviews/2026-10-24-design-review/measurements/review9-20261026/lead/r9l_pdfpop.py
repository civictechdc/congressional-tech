import duckdb
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs'
c=duckdb.connect('../validate-data/out/v9d.duckdb', read_only=True); q=lambda s:c.sql(s).fetchall()
c.sql(f"""create temp table leg2 as select regexp_extract(body_key,'([0-9a-f]{{64}})',1) sh,
  bool_or(status='completed' and body_format[1]='pdf' and coalesce(len(content_document_kind),0)>0) opened,
  bool_or(status='completed' and body_format[1]='pdf') completed_pdf, max(body_format[1]) fmt
  from read_parquet('{A}/readings/*.parquet', union_by_name=true) group by 1""")
c.sql("""create temp table p as select b.sh, b.bytes, b.sbytes,
  coalesce(chk.a_final,false) a, coalesce(chk.a_invalid,false) inv, coalesce(chk.a_final_after1001,false) a2,
  coalesce(l.opened,false) o, coalesce(l.completed_pdf,false) cp, l.fmt
  from body b left join chk using(sh) left join leg2 l using(sh)
  where b.media_pdf or b.sh in (select sh from leg2 where fmt='pdf')""")
def row(cond,label):
    r=q(f"select count(*), round(sum(sbytes)/1e9,1), round(sum(bytes)/1e9,1), round(median(bytes)/1e6,2) from p where {cond}")[0]
    print(f'{label:62s} n={r[0]:>7} storedGB={r[1]} contentGB={r[2]} medianMB={r[3]}')
row('true','population (media type PDF or legacy PDF reading)')
row('a','capture check (final response, written >= 10-01)')
row('a and inv and not exists (select 1)', 'placeholder')
row('a and not a2','  of which only 2026-10-01 lines')
row('a and inv','  of which a check found it damaged (any)')
row('not a and o','legacy, open proven (content_document_kind)')
row('not a and cp and not o','legacy completed, no proof of open')
row('not a and not cp',"neither")
row("not a and not cp and coalesce(fmt,'')='html'","  neither, legacy reads it as HTML")
row("not a and not o and coalesce(fmt,'')<>'html'","UNCHECKED under strict rule (not HTML)")
row("not a and not o and coalesce(fmt,'')<>'html' and bytes>10e6","  of which over 10 MB")
