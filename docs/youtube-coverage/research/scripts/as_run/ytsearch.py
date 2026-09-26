import re,json,sys,requests,time,itertools,concurrent.futures as cf,html
S=sys.argv[1]
names=["Agriculture","Appropriations","Armed Services","Budget","Education and Labor","Education and Workforce","Energy and Commerce","Ethics","Standards of Official Conduct","Financial Services","Foreign Affairs","International Relations","Homeland Security","House Administration","Judiciary","Natural Resources","Resources","Oversight and Government Reform","Oversight and Reform","Oversight and Accountability","Rules","Science Space and Technology","Science and Technology","Small Business","Transportation and Infrastructure","Veterans Affairs","Ways and Means","Intelligence","Energy Independence and Global Warming","Climate Crisis","Modernization of Congress","Benghazi","January 6th","Coronavirus Crisis","Coronavirus Pandemic","Weaponization","Economic Disparity","China","Strategic Competition China","Human Rights Commission"]
suffixes=["House Committee","Democrats","Republicans","GOP","Minority"]
qs=[f"House {n} Committee {s}" if s!="House Committee" else f"House Committee on {n}" for n in names for s in suffixes]
sess=requests.Session()
def search(q):
    for a in range(3):
        try:
            r=sess.get("https://www.youtube.com/results",params={"search_query":q,"sp":"EgIQAg=="},headers={"Accept-Language":"en-US"},timeout=30)
            t=r.text
            out=[]
            for m in re.finditer(r'"channelRenderer":\{"channelId":"(UC[\w-]{22})","title":\{"simpleText":"([^"]+)"\}(.{0,3000})',t):
                rest=m.group(3); h=re.search(r'"canonicalBaseUrl":"/(@[^"]+)"',rest)
                subs=re.search(r'"(?:videoCountText|subscriberCountText)":\{[^}]*"simpleText":"([^"]+)"',rest)
                out.append((m.group(1),json.loads('"'+m.group(2)+'"'),h.group(1) if h else '',subs.group(1) if subs else ''))
            return q,out
        except Exception: time.sleep(3)
    return q,[]
res={}
with cf.ThreadPoolExecutor(3) as p:
    for q,out in p.map(search,qs): res[q]=out
json.dump(res,open(f'{S}/ytsearch.json','w'))
print(len(qs),'queries,',sum(len(v) for v in res.values()),'results,',len({c[0] for v in res.values() for c in v}),'unique channels')
