import gzip, json, sys, glob, hashlib, collections as C
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/congress/meetings'
top=C.Counter(); rec=C.Counter(); nlines=C.Counter(); withcap=C.Counter(); withfr=C.Counter()
chamber=C.Counter(); jack=C.Counter(); jackzero=0; jackvals=C.Counter()
bykey=C.defaultdict(list); urlkinds=C.Counter(); rtype=C.Counter(); ret=C.Counter(); witness=C.Counter()
capfams=C.Counter()
for p in sorted(glob.glob(R+'/*/*.gz')):
    with gzip.open(p,'rt') as f:
        for i,l in enumerate(f):
            o=json.loads(l); nlines[p.split('meetings/')[1]]+=1
            for k in o: top[k]+=1
            r=o.get('record')
            rtype[type(r).__name__]+=1
            if not isinstance(r,dict): continue
            for k in r: rec[k]+=1
            if o.get('captures'): withcap[p]+=1
            if o.get('file_references'): withfr[p]+=1
            for c in o.get('captures') or []:
                capfams[(c.get('sha256') is not None, c.get('pointer') and str(c.get('pointer'))[:40])]+=1
            ch=r.get('chamber'); chamber[ch]+=1
            ht=r.get('hearingTranscript')
            if ht:
                jack[ch]+=1
                for h in ht:
                    jackvals[type(h.get('jacketNumber')).__name__]+=1
            if r.get('witnesses'): witness[ch]+=1
            if '_retrieved_at' in r: ret['_retrieved_at']+=1
            ev=r.get('eventId')
            body=json.dumps({k:v for k,v in r.items() if not k.startswith('_')},sort_keys=True,ensure_ascii=False,separators=(',',':'))
            full=json.dumps(r,sort_keys=True,ensure_ascii=False,separators=(',',':'))
            bykey[(ch,ev)].append((hashlib.sha256(body.encode()).hexdigest()[:16], hashlib.sha256(l.strip().encode()).hexdigest()[:16], r.get('updateDate'), p.split('meetings/')[1], i))
            u=r.get('_url') or ''
            urlkinds[u.split('?')[0].rsplit('/',3)[0] if u else None]+=1
print('lines',dict(nlines),sum(nlines.values()))
print('top',top.most_common())
print('record type',rtype)
print('record keys',rec.most_common())
print('withcap',dict(withcap)); print('withfr',dict(withfr)); print('capshape',capfams.most_common(10))
print('chamber',chamber); print('has hearingTranscript',jack, jackvals); print('has witnesses',witness)
print('urlkinds',urlkinds.most_common(8))
multi=[k for k,v in bykey.items() if len(v)>1]
print('distinct (chamber,eventId)',len(bykey),'keys with >1 line',len(multi))
diffbody=[k for k in multi if len({x[0] for x in bykey[k]})>1]
print('multi-line keys with differing record content (excl _ fields)',len(diffbody))
diffupd=[k for k in diffbody if len({x[2] for x in bykey[k]})>1]
print(' of which updateDate differs',len(diffupd))
samebody_dupline=sum(1 for k in multi if len({x[0] for x in bykey[k]})<len(bykey[k]))
print('keys with exact duplicate record content on 2+ lines',samebody_dupline)
for k in diffbody[:3]: print(k,bykey[k])
