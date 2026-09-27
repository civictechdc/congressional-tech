import re,requests,concurrent.futures as cf
bases=["agriculture","appropriations","armedservices","budget","edworkforce","energycommerce","financialservices","foreignaffairs","homeland","cha","judiciary","naturalresources","oversight","rules","science","smallbusiness","veterans","waysandmeans","transportation","intelligence","ethics","selectcommitteeontheccp"]
sites=[]
for b in bases:
    sites.append(f"https://{b}.house.gov")
    sites.append(f"https://democrats-{b}.house.gov")
sites+=["https://oversightdemocrats.house.gov","https://democrats-cha.house.gov"]
def get(u):
    try:
        r=requests.get(u,timeout=30,headers={"User-Agent":"Mozilla/5.0"})
        yt=sorted(set(m.rstrip('/"\'') for m in re.findall(r'https?://(?:www\.)?youtube\.com/(?:@[\w.-]+|c/[\w.-]+|user/[\w.-]+|channel/[\w-]+)',r.text)))
        return u,r.status_code,yt
    except Exception as e: return u,"ERR "+type(e).__name__,[]
with cf.ThreadPoolExecutor(8) as p:
    for u,c,yt in p.map(get,sites): print(u,c,yt)
