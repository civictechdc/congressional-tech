import sys,re,lxml.html,collections
DOC=re.compile(r'\.(pdf|docx?)($|\?)|/download/|/imo/media/|/files/',re.I)
for p in sys.argv[1:]:
    raw=open(p,'rb').read()
    try: root=lxml.html.fromstring(raw)
    except Exception as e: print(p,'parse',e); continue
    canon=root.xpath('//link[@rel="canonical"]/@href') or root.xpath('//meta[@property="og:url"]/@content')
    links=[a for a in root.xpath('//a[@href]') if DOC.search(a.get('href'))]
    blocks=collections.Counter(); ex=[]
    for a in links:
        cls=None
        for anc in a.iterancestors():
            c=(anc.get('class') or '').lower()
            if re.search(r'witness|person|participant|card|panel__|speaker|nominee',c):
                cls=c.split()[0]; break
        blocks[cls]+=1
        if len(ex)<3: ex.append((a.text_content().strip()[:40], cls))
    print(p.split('/')[-1], (canon or ['?'])[0][:90], 'doclinks',len(links), dict(blocks), ex)
