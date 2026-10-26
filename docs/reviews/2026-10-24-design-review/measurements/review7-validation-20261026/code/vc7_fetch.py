import sys,urllib.request,os
out=sys.argv[1]
for u in sys.argv[2:]:
    req=urllib.request.Request(u,headers={'User-Agent':'congressional-tech-review/1.0'})
    try:
        b=urllib.request.urlopen(req,timeout=30).read()
        name=u.split('://')[1].replace('/','_')
        open(os.path.join(out,name),'wb').write(b); print('ok',len(b),u)
    except Exception as e: print('ERR',u,e)
