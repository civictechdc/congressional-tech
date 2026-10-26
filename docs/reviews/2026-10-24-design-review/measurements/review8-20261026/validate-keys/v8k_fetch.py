import urllib.request,sys,time,hashlib,os
out=sys.argv[1]
for u in sys.argv[2:]:
    req=urllib.request.Request(u,headers={'User-Agent':'congressional-tech-review/1.0'})
    try:
        b=urllib.request.urlopen(req,timeout=40).read()
        p=os.path.join(out,hashlib.sha1(u.encode()).hexdigest()[:10]+'.html'); open(p,'wb').write(b)
        print('ok',len(b),p,u.split('?')[0])
    except Exception as e: print('ERR',type(e).__name__,str(e)[:80],u.split('?')[0])
    time.sleep(0.5)
