import duckdb
c=duckdb.connect('out/v9d.duckdb'); q=lambda s:c.sql(s).fetchall()
c.sql("""create or replace table pop as select b.sh, b.bytes, b.sbytes, b.media_pdf, coalesce(chk.a_final,false) a, lg.fmt, lg.st,
  exists(select 1 from leg where leg.sh=b.sh and leg.status='completed' and leg.fmt='pdf') l_pdf,
  exists(select 1 from leg where leg.sh=b.sh and leg.status='completed') l_any
  from body b left join chk using(sh) left join lg using(sh)
  where b.media_pdf or b.sh in (select sh from leg where fmt='pdf')""")
print('pop', q("select count(*), count(*) filter (where not media_pdf) from pop"))
print('extras legacy status', q("select st, fmt, count(*) from pop where not media_pdf group by all"))
for lab, cond in [('A|legacy completed pdf','a or l_pdf'),('A|legacy completed any fmt','a or l_any')]:
    r=q(f"select count(*) filter(where {cond}), count(*) filter(where not ({cond})), round(sum(sbytes) filter(where not ({cond}))/1e9,1), round(sum(bytes) filter(where not ({cond}))/1e9,1) from pop")
    print(lab, 'checked/unchecked/storedGB/contentGB', r)
print('gzip overhead where stored>content: max(stored-content), max content bytes', q("select max(sbytes-bytes), max(bytes) filter (where sbytes>bytes), median(bytes) filter (where sbytes>bytes) from body where sbytes>bytes"))
