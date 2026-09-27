import json,re,sys,os,glob,collections,requests,concurrent.futures as cf
S=sys.argv[1]
VID=re.compile(r'(?:youtube\.com/(?:watch\?(?:.*&)?v=|live/|embed/|shorts/)|youtu\.be/)([\w-]{11})')
# known videos -> handle
known={}
for f in glob.glob(f'{S}/d3/youtube_*.json'):
    for t,rows in json.load(open(f)).items():
        if t.startswith('youtube_videos_'):
            for v in rows.values(): known[v['videoId']]=t[15:]
meet=[json.loads(l) for l in open(f'{S}/meetings.jsonl')]
ok=[m for m in meet if 'eventId' in m]
print('meetings',len(meet),'ok',len(ok),'errors',collections.Counter(m.get('_status') for m in meet if 'eventId' not in m))
links=[]  # (eventId, congress, committee codes, videoId, other_url)
other=collections.Counter()
for m in ok:
    codes=[c.get('systemCode','') for c in m.get('committees',[])]
    for v in m.get('videos') or []:
        u=v.get('url','')
        mm=VID.search(u)
        if mm: links.append((m['eventId'],m['congress'],codes,mm.group(1),m.get('date','')[:10],m.get('title','')))
        elif 'congress.gov/event' not in u: other[re.sub(r'^https?://(www\.)?','',u).split('/')[0]]+=1
print('meetings with a youtube link:',len({l[0] for l in links}),'links',len(links),'non-youtube hosts',other.most_common(8))
unknown=sorted({l[3] for l in links if l[3] not in known})
print('known videos',sum(1 for l in links if l[3] in known),'unknown video ids',len(unknown))
cache_f=f'{S}/oembed.json'; cache=json.load(open(cache_f)) if os.path.exists(cache_f) else {}
sess=requests.Session()
def oe(v):
    try:
        r=sess.get('https://www.youtube.com/oembed',params={'url':f'https://www.youtube.com/watch?v={v}','format':'json'},timeout=30)
        if r.status_code==200: d=r.json(); return v,{'author':d['author_name'],'url':d['author_url'],'title':d['title']}
        return v,{'status':r.status_code}
    except Exception as e: return v,{'status':type(e).__name__}
todo=[v for v in unknown if v not in cache]
with cf.ThreadPoolExecutor(8) as p:
    for v,res in p.map(oe,todo): cache[v]=res
json.dump(cache,open(cache_f,'w'))
json.dump(links,open(f'{S}/links.json','w'))
byauth=collections.Counter(); status=collections.Counter()
for v in unknown:
    r=cache[v]
    if 'url' in r: byauth[r['url'].replace('https://www.youtube.com/','')]+=1
    else: status[r['status']]+=1
print('unknown resolved by channel:'); [print(f'  {n:5} {a}') for a,n in byauth.most_common(60)]
print('unresolvable:',status)
