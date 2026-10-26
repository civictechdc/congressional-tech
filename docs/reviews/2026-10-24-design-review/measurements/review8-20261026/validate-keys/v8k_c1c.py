import duckdb,sys
D=sys.argv[1]; c=duckdb.connect()
I='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes'
def q(s,lim=15):
    print('>>',s.replace(I+'/','').replace(D+'/','')[:260])
    for r in c.sql(s).fetchall()[:lim]: print('  ',r)
c.sql(f"create table k as select lower(system_code) sc from '{D}/committees.parquet'")
for tab in ['documents','document-filenames']:
  for col in ['committee_code','source_committee_code','source_publisher_committee_code']:
    T=f"'{I}/{tab}.parquet'"
    q(f"select count(*) filter (where len({col})>0) rows_with, count(*) from {T}")
    q(f"select length(u) l, regexp_matches(u,'^[A-Z]{{2}}[0-9]{{2}}$') hcode, regexp_matches(u,'^[a-z]{{4}}[0-9]{{2}}$') sys, count(*) from (select unnest({col}) u from {T}) group by all order by 4 desc",6)
    # direct match to spicy system codes, as-is and with hs prefix (the House registry form)
    q(f"select count(*) as n, count(*) filter (where lower(u) in (select sc from k)) as direct, count(*) filter (where 'hs'||lower(u) in (select sc from k)) as hsprefixed from (select unnest({col}) u from {T})")
    q(f"select u, count(*) from (select unnest({col}) u from {T}) where lower(u) not in (select sc from k) and 'hs'||lower(u) not in (select sc from k) group by 1 order by 2 desc",8)
