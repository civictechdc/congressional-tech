import duckdb,sys
D=sys.argv[1]+'/'
c=duckdb.connect()
def q(s):
    for r in c.sql(s).fetchall(): print('  ',r)
c.sql(f"create view v as select vote_id, congress, question, result, unnest(documents) d from '{D}roll_call_votes.parquet' where len(documents)>0")
c.sql(f"create view pn as select vote_id, congress, question, result, d.name nm from v where d.type='PN'")
print('PN names by number of votes naming them'); q("select n, count(*) from (select congress, nm, count(*) n from pn group by all) group by 1 order by 1")
q("select nm, list(question order by vote_id) from pn where congress=119 group by nm having count(*)>1 limit 3")
print('nominations 119: how many named by any vote'); 
q(f"select count(*), count(*) filter (where citation in (select nm from pn where congress=119)), count(*) filter (where latest_action_text ilike '%Record Vote Number%') , count(*) filter (where latest_action_text ilike '%confirmed%') from '{D}nominations.parquet'")
q(f"select vote_id, question, [x.name for x in documents] from '{D}roll_call_votes.parquet' where vote_id like '119-senate-%-225'")
print('committee official names colliding (any history name used by 2+ codes)')
q(f"""select count(*) from (select h.officialName n, count(distinct system_code) k from (select system_code, unnest(history) h from '{D}committees.parquet') group by 1 having k>1)""")
q(f"""select h.officialName n, list(distinct system_code) from (select system_code, unnest(history) h from '{D}committees.parquet') group by 1 having count(distinct system_code)>1 order by len(list(distinct system_code)) desc limit 8""")
