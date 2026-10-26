import pyarrow.parquet as pq,sys,collections,unicodedata,re
t=pq.read_table(sys.argv[1]+'/committees.parquet').to_pylist()
def norm(s): return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',s)).strip().casefold()
off=collections.defaultdict(set); raw=collections.defaultdict(set); both=collections.defaultdict(set)
for r in t:
    raw[r['name']].add(r['system_code']); both[norm(r['name'])].add(r['system_code'])
    for h in r['history'] or []:
        if h.get('officialName'):
            off[h['officialName']].add(r['system_code']); off_n=norm(h['officialName']); both[off_n].add(r['system_code'])
offn=collections.defaultdict(set)
for k,v in off.items(): offn[norm(k)]|=v
print('officialName raw collisions',sum(1 for v in off.values() if len(v)>1),'normalized',sum(1 for v in offn.values() if len(v)>1))
print('any name (name or official, normalized) shared by 2+ codes', sum(1 for v in both.values() if len(v)>1))
# codes sharing a displayable name with another code
codes=set()
for v in both.values():
    if len(v)>1: codes|=v
print('codes whose some name is shared', len(codes), 'of', len(t))
