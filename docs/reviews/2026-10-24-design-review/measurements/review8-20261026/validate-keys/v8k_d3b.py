import pyarrow.parquet as pq,sys,datetime as dt
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York')
t=pq.read_table(sys.argv[1]+'/committees.parquet').to_pylist()
def d(s):
    if not s: return dt.date.max
    return dt.datetime.fromisoformat(s.replace('Z','+00:00')).astimezone(ET).date()
for mode in ('halfopen','closed'):
    pairs=0; codes=set(); ident=0; dup=0
    for r in t:
        iv=[(d(h['startDate']),d(h.get('endDate')),h['officialName']) for h in r['history'] or [] if h.get('officialName') and h.get('startDate')]
        for i in range(len(iv)):
            for j in range(i+1,len(iv)):
                a,b=iv[i],iv[j]
                ov = (a[0]<b[1] and b[0]<a[1]) if mode=='halfopen' else (a[0]<=b[1] and b[0]<=a[1])
                if ov:
                    pairs+=1; codes.add(r['system_code'])
                    if a[2]==b[2]: ident+=1
                    if a[:2]==b[:2]: dup+=1
    print(mode,'Eastern day pairs',pairs,'codes',len(codes),'same-name',ident,'identical interval',dup)
# entries with officialName but no startDate, and codes with 2+ open-ended (no endDate) names
noopen=sum(1 for r in t if sum(1 for h in r['history'] or [] if h.get('officialName') and not h.get('endDate'))>1)
print('codes with 2+ open-ended official names',noopen)
