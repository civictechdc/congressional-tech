import csv,json,re,collections,datetime as dt,sys,random
S=sys.argv[1]
STOP=set("the a an of and to in on for with from at by is are be as or its it this that hearing hearings subcommittee committee house u.s. us part examining examine review oversight".split())
def words(s): return {w for w in re.findall(r"[a-z0-9]+",s.lower()) if w not in STOP and len(w)>2}
chan=list(csv.DictReader(open('packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv')))
vids=collections.defaultdict(list); by_event={}
for i,row in enumerate(chan):
    import os
    if not os.path.exists(f"{S}/d3/youtube_{i:02d}.json"): continue
    d=json.load(open(f'{S}/d3/youtube_{i:02d}.json'))
    for t,rows in d.items():
        if not t.startswith('youtube_videos_'): continue
        for v in rows.values():
            day=dt.date.fromisoformat(v['publishedAt'][:10]); v['_h']=t[15:]; v['_w']=words(v['title'])
            vids[row['systemCode']].append((day,v))
            for e in re.findall(r'(?<!\d)(1\d{5})(?!\d)', v['title']+' '+v['description']): by_event.setdefault(e,v)
gpo=list(csv.DictReader(open('apps/committee_youtube/data/gpo_hearings.csv')))
tracked={r["systemCode"] for i,r in enumerate(chan) if os.path.exists(f"{S}/d3/youtube_{i:02d}.json")}
res=[]
for r in gpo:
    how='';best=None;score=0
    if r['event_id'] and r['event_id'] in by_event: how='event_id'; best=by_event[r['event_id']]
    elif r['committee_code'] in tracked:
        h=dt.date.fromisoformat(r['held_date']); gw=words(r['title']); score=-1
        subs=[words(x) for x in r['subcommittees'].split(';') if x.strip()]
        sub_hit=None
        for d,v in vids[r['committee_code']]:
            if -1<=(d-h).days<=3:
                s=len(gw&v['_w'])/max(1,min(len(gw),len(v['_w'])))
                if s>score: score,best=s,v
                ## generic titles like "Oversight Hearing | Federal Lands Subcommittee"
                if subs and sub_hit is None and any(sw and sw<=v['_w'] for sw in subs): sub_hit=v
        if best is not None and score>=0.5: how='date+title'
        elif sub_hit is not None: how='date+subcommittee'; best=sub_hit
        elif best is not None: how='date_only'
    res.append((r,how,best,score))
print(collections.Counter(h for _,h,_,_ in res))
random.seed(3)
for label in ['date+subcommittee','date_only']:
    print('\n==',label)
    for r,h,b,s in random.sample([x for x in res if x[1]==label],6):
        print(f"  {r['held_date']} GPO: {r['title'][:70]}\n             YT : {b['publishedAt'][:10]} {b['title'][:70]} ({s:.2f})")
json.dump([(r['package_id'],h,(b or {}).get('videoId'),s) for r,h,b,s in res],open(f'{S}/matched2.json','w'))
