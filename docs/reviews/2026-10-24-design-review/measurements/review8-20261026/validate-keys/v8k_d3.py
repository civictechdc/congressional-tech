import pyarrow.parquet as pq,sys,collections,datetime as dt,re
t=pq.read_table(sys.argv[1]+'/committees.parquet').to_pylist()
def p(s):
    if not s: return None
    return dt.datetime.fromisoformat(s.replace('Z','+00:00'))
fmt=collections.Counter(); hours=collections.Counter(); raw_examples=set()
overl_pairs=0; codes_with=set(); diffname_pairs=0; samename=0; ex=[]
for r in t:
    H=[h for h in (r['history'] or [])]
    for h in H:
        for f in ('startDate','endDate'):
            s=h.get(f)
            if s:
                fmt[re.sub(r'\d','9',s)]+=1
                d=p(s); hours[d.hour if d.tzinfo else 'naive']+=1
    named=[h for h in H if h.get('officialName')]
    iv=[(p(h['startDate']), p(h.get('endDate')) or dt.datetime.max.replace(tzinfo=dt.timezone.utc), h['officialName']) for h in named if h.get('startDate')]
    for i in range(len(iv)):
        for j in range(i+1,len(iv)):
            a,b=iv[i],iv[j]
            if a[0] < b[1] and b[0] < a[1]:   # strict overlap
                overl_pairs+=1; codes_with.add(r['system_code'])
                if a[2]!=b[2]: diffname_pairs+=1
                else: samename+=1
                if len(ex)<4: ex.append((r['system_code'],a,b))
    # also touching (end == start) which a closed interval date lookup would see twice
print('date formats',fmt.most_common(6))
print('UTC hour distribution',sorted(hours.items(),key=lambda x:str(x[0])))
print('overlapping pairs',overl_pairs,'codes',len(codes_with),'different-name pairs',diffname_pairs,'same-name',samename)
for e in ex: print('  ',e[0],e[1][2],e[1][0].date(),e[1][1].date(),'|',e[2][2],e[2][0].date(),e[2][1].date())
# day-level overlap as model would see after date32 conversion (closed intervals on dates, Eastern)
