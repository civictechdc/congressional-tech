import duckdb
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs'
c=duckdb.connect('out/v9d.duckdb')
q=lambda s: c.sql(s).fetchall()
c.sql(f"""create or replace table body as select sha256 sh, max(bytes) bytes, max(stored_bytes) sbytes, bool_or(media_type ilike '%pdf%') media_pdf from '{A}/captures.parquet' where sha256 is not null group by 1""")
c.sql(f"""create or replace table leg as select regexp_extract(body_key,'([0-9a-f]{{64}})',1) sh, status, body_format[1] fmt from read_parquet('{A}/readings/*.parquet', union_by_name=true)""")
print('pdf by media', q("select count(*) from body where media_pdf"))
print('pdf by media or legacy pdf reading', q("select count(*) from body where media_pdf or sh in (select sh from leg where fmt='pdf')"))
# receipt rows with a written date: documents dir date, else filename date
c.sql("""create or replace table rr as select *, coalesce(nullif(regexp_extract(ddir,'^(\\d{4}-\\d{2}-\\d{2})$',1),''),
   strftime(strptime(nullif(regexp_extract(rel,'(20\\d{6})',1),''),'%Y%m%d'),'%Y-%m-%d')) wdate from rc""")
c.sql("""create or replace table chk as select sh,
  bool_or(ptr='["content","body"]' and outcome in ('saved','invalid_document') and wdate>='2026-10-01') a_final,
  bool_or(ptr='["content","body"]' and outcome in ('saved','invalid_document') and wdate>'2026-10-01') a_final_after1001,
  bool_or(outcome in ('saved','invalid_document') and wdate>='2026-10-01') b_any_dated,
  bool_or(outcome in ('saved','invalid_document')) b_any_undated,
  bool_or(ptr='["content","body"]' and outcome='invalid_document' and wdate>='2026-10-01') a_invalid,
  bool_or(ptr='["content","body"]' and outcome in ('saved','invalid_document') and rdate>='2026-10-01') a_final_rdate
  from rr group by sh""")
c.sql("create or replace table lg as select sh, bool_or(status='completed' and fmt='pdf') legacy_ok, max(fmt) fmt, string_agg(distinct status) st from leg group by sh")
c.sql("""create or replace table pdf as select b.*, coalesce(a_final,false) a, coalesce(a_final_after1001,false) a2, coalesce(b_any_dated,false) b1, coalesce(b_any_undated,false) b2, coalesce(a_final_rdate,false) ar,
   coalesce(legacy_ok,false) l, lg.fmt, lg.st from body b left join chk using(sh) left join lg using(sh) where media_pdf""")
print('N, A, legacy, A&legacy, A|legacy, unchecked', q("select count(*), count(*) filter(where a), count(*) filter(where l), count(*) filter(where a and l), count(*) filter(where a or l), count(*) filter(where not (a or l)) from pdf"))
print('A with retrieved_at date instead', q("select count(*) filter(where ar), count(*) filter(where not (ar or l)) from pdf"))
print('only-2026-10-01 lines (A but not A after 10-01, no legacy?)', q("select count(*) filter(where a and not a2), count(*) filter(where a and not a2 and not l) from pdf"))
print('B1 any entry dated>=10-01: checked, +legacy, unchecked', q("select count(*) filter(where b1), count(*) filter(where b1 or l), count(*) filter(where not(b1 or l)), count(*) filter(where not b1) from pdf"))
print('B2 any entry any date: checked, unchecked, unchecked w/o legacy', q("select count(*) filter(where b2), count(*) filter(where not (b2 or l)), count(*) filter(where not b2) from pdf"))
def dist(cond, label):
    r=q(f"""select count(*), round(sum(bytes)/1e9,1), round(sum(sbytes)/1e9,1), round(median(bytes)/1e6,2), round(100.0*avg((bytes>10e6)::int),1), count(*) filter (where bytes>64*1024*1024) from pdf where {cond}""")
    print(f'  {label:45s} n={r[0][0]} GB={r[0][1]} storedGB={r[0][2]} median_MB={r[0][3]} pct>10MB={r[0][4]} >64MiB={r[0][5]}')
print('size distributions (content bytes; decimal MB)')
dist('a or l','checked (A|legacy)')
dist('not (a or l)','unchecked (A reading)')
dist("not (a or l) and coalesce(fmt,'')<>'html'",'unchecked, excl legacy-html')
dist("not (b1 or l)",'unchecked (B1 reading)')
print('unchecked by legacy fmt/status', q("select fmt, st, count(*) from pdf where not (a or l) group by all order by 3 desc"))
