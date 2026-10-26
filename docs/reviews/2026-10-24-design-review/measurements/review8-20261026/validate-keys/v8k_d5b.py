import pyarrow.parquet as pq,sys,datetime as dt,collections
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York'); D=sys.argv[1]
def census(vals,label):
    n=diff=0; ex=None
    for s in vals:
        if not s or len(s)<11: continue
        x=dt.datetime.fromisoformat(s.replace('Z','+00:00')); n+=1
        if x.date()!=x.astimezone(ET).date():
            diff+=1; ex=ex or s
    print(label,'instants',n,'UTC date != Eastern date',diff,ex)
t=pq.read_table(D+'/committees.parquet').to_pylist()
census([h.get(f) for r in t for h in r['history'] or [] for f in ('startDate','endDate')],'committees.history')
census(pq.read_table(D+'/bill_vote_references.parquet').column('date').to_pylist(),'bill_vote_references.date')
census(pq.read_table(D+'/committee_meetings.parquet').column('meeting_date').to_pylist(),'committee_meetings.meeting_date')
# roll_call_votes vote_day vs bill_vote_references date for same vote
import duckdb
c=duckdb.connect()
print(c.sql(f"""select count(*), count(*) filter (where substr(b.date,1,10)<>v.vote_day) utc_mismatch,
 count(*) filter (where cast(timezone('America/New_York', cast(b.date as timestamptz)) as date)::varchar<>v.vote_day) et_mismatch
 from '{D}/bill_vote_references.parquet' b join '{D}/roll_call_votes.parquet' v on b.congress||'-'||b.chamber||'-'||b.session||'-'||b.roll_number=v.vote_id""").fetchall())
