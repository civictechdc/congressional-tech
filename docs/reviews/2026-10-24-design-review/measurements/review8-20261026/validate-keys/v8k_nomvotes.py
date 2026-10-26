import duckdb,sys
D=sys.argv[1]; c=duckdb.connect()
def q(s,lim=25):
    print('>>',s.replace(D+'/','')[:250])
    for r in c.sql(s).fetchall()[:lim]: print('  ',r)
c.sql(f"create view n as select * from '{D}/nominations.parquet'")
c.sql(f"create view v as select * from '{D}/roll_call_votes.parquet'")
# raw vote-document occurrences, NOT deduplicated
c.sql("""create table vd as select vote_id, v.congress vc, coalesce(cast(d.congress as varchar), v.congress) dc, d.number num, d.name nm, question, result, vote_date from (select *, unnest(documents) d from v where chamber='senate') v where d.type='PN'""")
q("select count(*), count(distinct vote_id), count(distinct (dc,num)) from vd")
q("select count(*) from vd where dc='119'")
q("select count(*) from (select vote_id, dc, num, count(*) k from vd group by all having k>1)")
# per nomination: distinct votes naming exactly its citation
c.sql("""create table nv as select n.citation, n.number, n.part_number, n.latest_action_text, count(distinct vd.vote_id) k from n left join vd on vd.dc=n.congress and 'PN'||vd.num=n.citation group by all""")
q("select case when k>=3 then '3+' else cast(k as varchar) end b, count(*) from nv group by 1 order by 1")
q("select count(*) from nv where k>=1")
q("select count(*) from nv where k>=2")
# votes naming a citation not in nominations (orphans) for 119th
q("select count(*), count(distinct num) from vd where dc='119' and 'PN'||num not in (select citation from n)")
q("select num from vd where dc='119' and 'PN'||num not in (select citation from n) limit 5")
# confirmed status
q("select regexp_extract(latest_action_text,'^(\\w+ ?\\w*)',1) a, count(*) from nv group by 1 order by 2 desc",12)
q("select count(*) from nv where latest_action_text ilike '%confirmed%'")
q("select k>0, count(*) from nv where latest_action_text ilike '%confirmed%' group by 1")
q("select count(*) from nv where latest_action_text ilike '%confirmed%' and latest_action_text ilike '%voice vote%'")
q("select count(*) from nv where latest_action_text ilike '%confirmed%' and latest_action_text ilike '%unanimous consent%'")
q("select count(*) from nv where latest_action_text ilike '%confirmed%' and k=0 and (latest_action_text ilike '%Yea-Nay%' or latest_action_text ilike '%record vote%')")
q("select latest_action_text from nv where latest_action_text ilike '%confirmed%' and k=0 and latest_action_text ilike '%vote%' limit 3")
# question mix for multi-vote nominations
q("select question, count(*) from vd where dc='119' group by 1 order by 2 desc",10)
# a single vote naming several nominations (en bloc)
q("select case when c>=10 then '10+' else cast(c as varchar) end, count(*) from (select vote_id, count(distinct num) c from vd group by 1) group by 1 order by 1")
q("select case when k>=3 then '3+' else cast(k as varchar) end, count(*) from (select dc,num,count(distinct vote_id) k from vd group by all) group by 1 order by 1")
q("select count(*) from (select dc,num, count(distinct vote_id) filter (where question='On the Nomination') k from vd group by all) where k>=2")
q("select count(*) from (select dc,num, count(distinct vote_id) filter (where question='On the Nomination') k from vd group by all) where k=0")
# part-less vote on a multi-part nomination
q("select count(*) from vd v where dc='119' and not regexp_matches(num,'-') and exists (select 1 from n where n.number=v.num and n.part_number<>'00')")
