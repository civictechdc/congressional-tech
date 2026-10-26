import duckdb,sys,json
D=sys.argv[1]; c=duckdb.connect()
def q(s,lim=8):
    print('>>',s.replace(D+'/','')[:220])
    for r in c.sql(s).fetchall()[:lim]: print('  ',str(r)[:400])
N=f"'{D}/nominations.parquet'"
q(f"select count(*), count(*) filter (where hearings_json is not null and hearings_json not in ('[]','null','')) , count(*) filter (where committees_json is not null and committees_json not in ('[]','null','')) from {N}")
q(f"select hearings_json from {N} where hearings_json not in ('[]','null','') limit 2")
q(f"select committees_json from {N} where committees_json not in ('[]','null','') limit 1")
# hearing link keys in nominations: what identifiers?
rows=c.sql(f"select hearings_json from {N} where hearings_json not in ('[]','null','')").fetchall()
keys=set(); n=0; jackets=0; events=0
for (h,) in rows:
    for e in json.loads(h):
        n+=1; keys|=set(e.keys()); jackets+=bool(e.get('jacketNumber')); events+=bool(e.get('eventId') or e.get('meetingId'))
print('hearing entries',n,'keys',keys,'with jacket',jackets,'with event',events)
B=f"'{D}/bill_committees.parquet'"
q(f"select count(*), count(distinct bill_id), count(distinct system_code), count(*) filter (where system_code is null) from {B}")
q(f"select min(split_part(bill_id,'-',1)::int), max(split_part(bill_id,'-',1)::int) from {B}")
q(f"select count(*) from (select distinct system_code from {B}) where system_code not in (select system_code from '{D}/committees.parquet')")
q(f"select count(distinct bill_id) from '{D}/congress_bills.parquet' where split_part(bill_id,'-',1)::int>=(select min(split_part(bill_id,'-',1)::int) from {B})")
R=f"'{D}/committee_reports.parquet'"
q(f"select count(*), min(congress), max(congress), count(bill_id), count(distinct package_id) from {R}")
q(f"select package_id, congress, report_type, chamber, bill_id from {R} limit 3")
M=f"'{D}/committee_meetings.parquet'"
q(f"select count(*), min(congress), max(congress), count(*) filter (where nomination_references_json not in ('[]','null','')) from {M}")
q(f"select nomination_references_json from {M} where nomination_references_json not in ('[]','null','') limit 1")
