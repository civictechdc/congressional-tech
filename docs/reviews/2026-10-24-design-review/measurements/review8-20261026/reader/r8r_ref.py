import duckdb,sys
D=sys.argv[1]+'/'
c=duckdb.connect()
def q(s):
    for r in c.sql(s).fetchall(): print('  ',r)
print('committees: rows, distinct names, names shared by >1 system_code')
q(f"select count(*), count(distinct name) from '{D}committees.parquet'")
q(f"select name, count(*), list(system_code) from '{D}committees.parquet' group by 1 having count(*)>1 order by 2 desc limit 12")
q(f"select count(*) from (select name from '{D}committees.parquet' group by 1 having count(*)>1)")
print('history sample'); q(f"select system_code, name, history from '{D}committees.parquet' where history_count>1 limit 2")
print('assignments congress'); q(f"select congress, chamber, count(*) from '{D}committee_assignments.parquet' group by all")
q(f"select position, count(*) from '{D}committee_assignments.parquet' group by 1 order by 2 desc limit 8")
print('nominations'); q(f"select congress, count(*) from '{D}nominations.parquet' group by 1")
q(f"select citation, number, part_number, latest_action_text, hearings_json from '{D}nominations.parquet' where hearings_json is not null and hearings_json<>'[]' limit 3")
q(f"select count(*) filter (where hearings_json is not null and hearings_json<>'[]'), count(*) from '{D}nominations.parquet'")
print('votes documents'); q(f"select vote_id, documents, bill_id from '{D}roll_call_votes.parquet' where len(documents)>0 limit 4")
q(f"select vote_id from '{D}roll_call_votes.parquet' using sample 3")
