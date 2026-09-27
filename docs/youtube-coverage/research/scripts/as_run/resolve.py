import re,sys,json,requests,concurrent.futures as cf,html
def resolve(path):
    u="https://www.youtube.com/"+path
    try:
        r=requests.get(u,timeout=30,headers={"Accept-Language":"en-US","User-Agent":"Mozilla/5.0"})
    except Exception as e: return path,{"err":type(e).__name__}
    if r.status_code!=200: return path,{"status":r.status_code}
    t=r.text
    g=lambda p:(m.group(1) if (m:=re.search(p,t)) else "")
    return path,{"id":g(r'"externalId":"(UC[\w-]+)"') or g(r'<link rel="canonical" href="https://www.youtube.com/channel/(UC[\w-]+)"'),
        "handle":g(r'"vanityChannelUrl":"http://www.youtube.com/(@[^"]+)"') or g(r'"canonicalBaseUrl":"/(@[^"]+)"'),
        "title":html.unescape(g(r'<meta property="og:title" content="([^"]*)"')),
        "subs":g(r'"(\d[\d.,KM]*) subscribers"'),"videos":g(r'"(\d[\d,]*) videos"')}
paths=[l.strip() for l in open(sys.argv[1]) if l.strip()]
out={}
with cf.ThreadPoolExecutor(6) as p:
    for path,info in p.map(resolve,paths):
        out[path]=info; print(f"{path:45} {info}")
json.dump(out,open(sys.argv[1]+".json","w"),indent=1)
