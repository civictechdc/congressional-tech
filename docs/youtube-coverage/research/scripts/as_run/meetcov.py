import csv,json,re,sys,glob,collections,datetime as dt
S=sys.argv[1]; D=sys.argv[2]
STOP=set("the a an of and to in on for with from at by is are be as or its it this that hearing hearings subcommittee committee house u.s. us part examining examine review oversight markup meeting full".split())
words=lambda s:{w for w in re.findall(r"[a-z0-9]+",s.lower()) if w not in STOP and len(w)>2}
chan=list(csv.DictReader(open('packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv')))
vids=collections.defaultdict(list); by_event={}; allids=set()
for i,row in enumerate(chan):
    try: d=json.load(open(f'{D}/youtube_{i:02d}.json'))
    except FileNotFoundError: continue
    for t,rows in d.items():
        if not t.startswith('youtube_videos_'): continue
        for v in rows.values():
            allids.add(v['videoId']); v['_w']=words(v['title'])
            vids[row['systemCode']].append((dt.date.fromisoformat(v['publishedAt'][:10]),v))
            for e in re.findall(r'(?<!\d)(1\d{5})(?!\d)',v['title']+' '+v['description']): by_event.setdefault(e,v)
VID=re.compile(r'(?:youtube\.com/(?:watch\?(?:.*&)?v=|live/|embed/|shorts/|v/)|youtu\.be/)([\w-]{11})')
ALIAS={'jjec00':'jsec00','hlvc00':'hsgo00','hlfd00':'hsju00','hlqj00':'hsju00'}
res=collections.defaultdict(collections.Counter); none=[]
for l in open(f'{S}/meetings.jsonl'):
    m=json.loads(l)
    if m.get('meetingStatus') not in ('Scheduled','Rescheduled'): continue
    codes=[c['systemCode'] for c in m.get('committees',[])]
    parents=[ALIAS.get(c[:4]+'00',c[:4]+'00') for c in codes]
    subs=[c.get('name','') for c in m.get('committees',[]) if not c['systemCode'].endswith('00')]
    links=[VID.search(v.get('url','')).group(1) for v in (m.get('videos') or []) if VID.search(v.get('url',''))]
    day=dt.date.fromisoformat(m['date'][:10]); how=''
    if links: how='congress.gov link' + ('' if any(x in allids for x in links) else ' (unlisted/other)')
    elif m['eventId'] in by_event: how='event id in video'
    else:
        tw=words(m.get('title','')); sw=[words(re.sub(r'^.*?Subcommittee on ','',s)) for s in subs]; best=-1; subhit=False; any_day=False
        for p in parents:
            for d_,v in vids.get(p,[]):
                if -1<=(d_-day).days<=3:
                    any_day=True
                    s=len(tw&v['_w'])/max(1,min(len(tw),len(v['_w']))); best=max(best,s)
                    if any(x and x<=v['_w'] for x in sw): subhit=True
        how='date+title' if best>=0.5 else 'date+subcommittee' if subhit else 'possible (date only)' if any_day else ('committee not tracked' if not any(p in vids for p in parents) else 'no video found')
    res[m['congress']][how]+=1
    if how=='no video found': none.append((m['date'][:10],parents[0] if parents else '',m.get('type'),m.get('title','')[:90]))
order=['congress.gov link','congress.gov link (unlisted/other)','event id in video','date+title','date+subcommittee','possible (date only)','no video found','committee not tracked']
print('congress '+' | '.join(o[:14] for o in order))
for c in sorted(res): print(c, [res[c][o] for o in order], sum(res[c].values()))
json.dump(none,open(f'{S}/meet_none.json','w'))
print('no video found by committee (116+):',collections.Counter(n[1] for n in none if n[0]>='2019').most_common(12))
print('by type:',collections.Counter(n[2] for n in none if n[0]>='2019'))
