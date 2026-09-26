import csv,json,re,sys,collections
sys.path.insert(0,sys.argv[1]+'/swarm'); import yt
STOP=set("the a an of and to in on for with from at by is are be as or its it this that hearing hearings subcommittee committee house u.s. us part examining examine review oversight markup meeting full".split())
W=lambda s:{w for w in re.findall(r"[a-z0-9]+",(s or '').lower()) if w not in STOP and len(w)>2}
def mins(l):
    p=[int(x) for x in l.split(':')] if l and re.fullmatch(r'[\d:]+',l) else []
    return (p[0]*60+p[1]+p[2]/60 if len(p)==3 else p[0]+p[1]/60 if len(p)==2 else 0)
gpo={r['package_id']:r for r in csv.DictReader(open('apps/committee_youtube/data/gpo_hearings.csv'))}
rows=[r for r in csv.DictReader(open('apps/committee_youtube/data/gpo_hearing_videos.csv'))
      if int(r['congress'])>=113 and r['chamber'] in('house','joint') and r['status'] in('no_video_found','clips_only')]
tracked={h.lower() for c in csv.DictReader(open('packages/congress_shared/src/congress_shared/youtube/youtube-accounts.csv')) for h in [c['handle']]+c['secondary'].split(';')+(c.get('member_channels') or '').split(';') if h.strip()}
out=[]
for i,r in enumerate(rows):
    g=gpo[r['package_id']]; title=re.sub(r'^\[[^\]]*\]\s*','',g['title']); tw=W(title)
    short=' '.join(title.split()[:10]); year=g['held_date'][:4]
    hits={}
    for src,res in [('search',yt.search(f'{short} hearing {year}'))]+[(ch,yt.channel_search(ch,short)) for ch in ('@RollCall','@washingtonpost','@PBSNewsHour')]:
        for v in res:
            m=mins(v['length']); sim=len(tw&W(v['title']))/max(1,min(len(tw),10))
            if m>=30 and sim>=0.3 and v['channel'].lower() not in tracked:
                hits[v['videoId']]={**v,'minutes':round(m),'sim':round(sim,2),'found_by':src}
    if hits: out.append({'package_id':r['package_id'],'held_date':g['held_date'],'committee':g['committee_name'],'title':g['title'],'status':r['status'],'transcript':g['html_url'],'candidates':sorted(hits.values(),key=lambda x:-x['sim'])[:5]})
    if i%50==0: print(i,len(rows),len(out),flush=True)
json.dump(out,open(sys.argv[1]+'/news_candidates.json','w'),indent=1)
print('DONE',len(rows),'hearings searched;',len(out),'with candidates')
