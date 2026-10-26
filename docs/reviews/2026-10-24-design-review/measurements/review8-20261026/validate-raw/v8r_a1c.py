import gzip, json, glob, collections as C, re
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
c=C.Counter(); jk=set(); hj=set(); senate_jk=set(); wrapped_keys=set(); base_keys=set(); det_ch=C.Counter()
for p in sorted(glob.glob(R+'congress/meetings/*/*.gz')):
    for l in gzip.open(p,'rt'):
        r=json.loads(l)['record']
        m=r.get('meeting') if isinstance(r.get('meeting'),dict) else None
        rr=m or r
        if 'eventId' in rr:
            (wrapped_keys if m else base_keys).add((rr['chamber'],rr['eventId']))
            for h in rr.get('hearingTranscript') or []:
                jk.add((rr['congress'],rr['chamber'],h.get('jacketNumber')))
        if r.get('final_url') and re.search(r'committee-meeting/\d+/\w+/\d+',r['final_url']): det_ch[r['final_url'].split('/')[-2]]+=1
for p in sorted(glob.glob(R+'**/*.gz',recursive=True)):
    if 'congress/meetings' in p: continue
    with gzip.open(p,'rt') as f:
        for l in f:
            if 'api.congress.gov/v3/hearing' not in l: continue
            o=json.loads(l); r=o.get('record') or o
            u=r.get('requested_url') or r.get('url') or ''
            if '/v3/hearing/' in u:
                has_body=bool(o.get('file_references') or o.get('captures') or r.get('sha256'))
                c[('hearing line', p.split('receipts/')[1].split('/')[0], has_body)]+=1
                m=re.search(r'/v3/hearing/(\d+)/(\w+)/(\d+)',u)
                if m: hj.add((int(m.group(1)),m.group(2),int(m.group(3))))
print(c); print('inline jackets',len(jk),'senate',sum(1 for x in jk if x[1]=='Senate'))
print('hearing-endpoint jackets',len(hj), C.Counter(x[1] for x in hj))
inl={(a,b.lower(),j) for a,b,j in jk}
print('hearing-endpoint jackets also inline',len(hj&inl))
print('wrapped keys',len(wrapped_keys),'new vs base',len(wrapped_keys-base_keys)); print('detail bodies by chamber',det_ch)
