import gzip,json,sys,glob,re,collections
R=sys.argv[1]
ev=collections.defaultdict(set); nc=collections.Counter(); partsp=collections.Counter()
for p in sorted(glob.glob(R+'/congress/meetings/**/*.jsonl.gz',recursive=True)):
    with gzip.open(p,'rt') as f:
        for l in f:
            r=json.loads(l).get('record') or {}
            if not isinstance(r,dict) or 'eventId' not in r: continue
            ev[str(r['eventId'])].add(r.get('chamber'))
            if r.get('chamber')=='NoChamber':
                for c in r.get('committees') or []: nc[(c.get('systemCode') or '')[:1]]+=1
            ri=r.get('relatedItems')
            if isinstance(ri,dict):
                for nm in ri.get('nominations') or []:
                    partsp[repr(nm.get('part'))]+=1
multi=[k for k,v in ev.items() if len(v)>1]
print('distinct eventIds',len(ev),'with >1 chamber',len(multi), multi[:5])
print('NoChamber committee code prefix',nc.most_common())
print('nomination part spellings',partsp.most_common(15))
