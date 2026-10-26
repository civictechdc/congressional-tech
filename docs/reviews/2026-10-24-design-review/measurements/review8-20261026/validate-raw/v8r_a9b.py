import gzip,json,glob,collections as C,re
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
for fam in ('house/witness-xml','house/meeting-xml'):
    c=C.Counter(); n=0
    for p in glob.glob(R+fam+'/*/*.gz'):
        for l in gzip.open(p,'rt'):
            n+=1
            for m in set(re.findall(r'docs\.house\.gov/(?:meetings|Committee/Calendar)[^"\s]*?/([A-Za-z]+)-[^"/\s]*?\.xml|ByEvent\.aspx\?EventID=\d+',l)): c[m or 'ByEvent']+=1
            if 'WList' in l: c['line mentions WList']+=1
            if '<committee-meeting' in l or 'committee-meeting' in l: c['line mentions committee-meeting']+=1
    print(fam,n,c.most_common(8))
