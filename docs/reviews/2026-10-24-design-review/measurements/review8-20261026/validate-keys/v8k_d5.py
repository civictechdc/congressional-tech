import pyarrow.parquet as pq,sys,collections,datetime as dt,re
D=sys.argv[1]
t=pq.read_table(D+'/committees.parquet').to_pylist()
for f in ('startDate','endDate'):
    hrs=collections.Counter()
    for r in t:
        for h in r['history'] or []:
            if h.get(f): hrs[int(h[f][11:13])]+=1
    tot=sum(hrs.values()); print(f, 'n',tot,'04-05h',hrs[4]+hrs[5], dict(sorted(hrs.items())))
# day-level closed-interval overlaps (UTC date and Eastern date)
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York')
def d(s,tz):
    if not s: return dt.date.max
    x=dt.datetime.fromisoformat(s.replace('Z','+00:00')); return x.astimezone(tz).date()
for tzname,tz in (('UTC',dt.timezone.utc),('Eastern',ET)):
    pairs=0
    for r in t:
        iv=[(d(h['startDate'],tz),d(h.get('endDate'),tz),h['officialName']) for h in r['history'] or [] if h.get('officialName') and h.get('startDate')]
        for i in range(len(iv)):
            for j in range(i+1,len(iv)):
                a,b=iv[i],iv[j]
                if a[0]<=b[1] and b[0]<=a[1]: pairs+=1
    print('closed day-level overlapping officialName pairs',tzname,pairs)
# all history entries (with or without officialName)
pairs=0
for r in t:
    iv=[(d(h['startDate'],dt.timezone.utc),d(h.get('endDate'),dt.timezone.utc)) for h in r['history'] or [] if h.get('startDate')]
    for i in range(len(iv)):
        for j in range(i+1,len(iv)):
            a,b=iv[i],iv[j]
            if a[0]<=b[1] and b[0]<=a[1]: pairs+=1
print('closed overlapping pairs, any entry',pairs)
# other spicy date columns: shape census over raw values
import duckdb
c=duckdb.connect()
for tab,cols in [('roll_call_votes',['vote_date','vote_day']),('nominations',['received_date','latest_action_date']),('congress_bills',['introduced_date','latest_action_date']),('bill_vote_references',['date']),('member_terms',['term_start','term_end']),('committee_meetings',['meeting_date'])]:
    for col in cols:
        r=c.sql(f"select regexp_replace({col},'[0-9]','9','g') s, count(*) from '{D}/{tab}.parquet' group by 1 order by 2 desc limit 3").fetchall()
        hh=c.sql(f"select substr({col},12,2) h, count(*) from '{D}/{tab}.parquet' where length({col})>10 group by 1 order by 2 desc limit 4").fetchall()
        print(tab,col,r,hh)
