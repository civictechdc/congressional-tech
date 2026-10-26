import gzip, json, glob, collections as C, re
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/congress/meetings/'
red=lambda s: re.sub(r'(api_key=)[^&"]+',r'\1R',s)
c=C.Counter(); shas=C.defaultdict(set); ex=[]
for p in sorted(glob.glob(R+'*/*.gz')):
    for i,l in enumerate(gzip.open(p,'rt')):
        o=json.loads(l); r=o['record']
        frs=o['file_references']
        if frs or 'meeting' in r or 'committeeMeetings' in r:
            kind=('fr' if frs else '')+('+meeting' if 'meeting' in r else '')+('+list' if 'committeeMeetings' in r else '')
            u=r.get('requested_url') or r.get('url') or r.get('_url')
            path=re.sub(r'\?.*','',u or '').replace('https://api.congress.gov/v3/','')
            segs=path.split('/')
            c[(p.split('meetings/')[1],kind,len(segs))]+=1
            for e in frs: shas[(p.split('meetings/')[1],len(segs))].add(e.get('sha256'))
            if len(ex)<4 and (frs or 'meeting' in r): ex.append((p.split('meetings/')[1],i,red(json.dumps({k:(v if not isinstance(v,(dict,list)) else type(v).__name__) for k,v in r.items()}))[:900], [ {k:e.get(k) for k in ('pointer_json','context_url','media_type','sha256','fidelity')} for e in frs][:2]))
print(c); print({k:len(v) for k,v in shas.items()})
allsha=set().union(*shas.values()); print('distinct body sha across all',len(allsha))
for e in ex: print(e)
