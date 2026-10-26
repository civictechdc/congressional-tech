import duckdb,sys
D=sys.argv[1]; c=duckdb.connect()
def q(s,lim=25):
    print('>>',s.replace(D+'/','')[:300])
    for r in c.sql(s).fetchall()[:lim]: print('  ',r)
N=f"'{D}/nominations.parquet'"; V=f"'{D}/roll_call_votes.parquet'"
q(f"select count(*), count(distinct citation), count(distinct (congress,number,part_number)) from {N}")
q(f"select congress, count(*) from {N} group by 1")
q(f"select part_number, count(*) from {N} group by 1 order by 2 desc",10)
q(f"select citation, congress, number, part_number from {N} where part_number<>'00' limit 5")
q(f"select regexp_matches(citation,'^PN[0-9]+(-[0-9]+)?$') ok, count(*) from {N} group by 1")
q(f"select count(*) from {N} where citation <> 'PN'||number||case when part_number='00' then '' else '-'||cast(cast(part_number as int) as varchar) end")
# vote documents raw
q(f"select d.type, d.congress is null cnull, count(*) from (select unnest(documents) d from {V} where chamber='senate') group by all order by 3 desc")
q(f"select d.type, count(*) from (select unnest(documents) d from {V} where chamber='house') group by all order by 2 desc",10)
q(f"select d.number, d.name, d.congress, v.congress from (select unnest(documents) d, congress from {V} where chamber='senate') v where d.type='PN' and regexp_matches(d.number,'-') limit 5")
q(f"select regexp_matches(d.number,'^[0-9]+(-[0-9]+)?$') ok, count(*) from (select unnest(documents) d from {V} where chamber='senate') where d.type='PN' group by 1")
q(f"select d.number from (select unnest(documents) d from {V} where chamber='senate') where d.type='PN' and not regexp_matches(d.number,'^[0-9]+(-[0-9]+)?$') limit 10")
q(f"select count(*) from (select unnest(documents) d, congress from {V} where chamber='senate') where d.type='PN' and d.congress is not null and cast(d.congress as varchar)<>congress")
