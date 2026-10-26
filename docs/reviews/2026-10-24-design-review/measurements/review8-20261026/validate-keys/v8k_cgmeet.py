import gzip,json,sys,glob,re,collections
R=sys.argv[1]
ch=collections.Counter(); urlch=collections.Counter(); pair=collections.Counter(); docch=collections.Counter(); n=0; keys=collections.Counter()
nomref=collections.Counter()
for p in sorted(glob.glob(R+'/congress/meetings/**/*.jsonl.gz',recursive=True)):
    with gzip.open(p,'rt') as f:
        for l in f:
            n+=1
            d=json.loads(l); r=d.get('record') or {}
            if not isinstance(r,dict): continue
            keys.update(r.keys())
            c=r.get('chamber'); ch[repr(c)]+=1
            u=r.get('_url') or ''
            m=re.search(r'committee-meeting/\d+/([^/?]+)/',u)
            uc=m.group(1) if m else None; urlch[repr(uc)]+=1
            pair[(repr(c),repr(uc))]+=1
            for md in (r.get('meetingDocuments') or [])+(r.get('witnessDocuments') or []):
                m2=re.search(r'congress\.gov/\d+/meeting/([^/]+)/',md.get('url') or '')
                if m2: docch[m2.group(1)]+=1
            for nm in (r.get('relatedItems') or {}).get('nominations',[]) if isinstance(r.get('relatedItems'),dict) else []:
                nomref[json.dumps(sorted(nm.keys()))]+=1
print('lines',n); print('record.chamber',ch.most_common()); print('_url chamber',urlch.most_common()); print('pairs',pair.most_common())
print('doc url chamber',docch.most_common()); print('record keys',keys.most_common(40)); print('nom ref shapes',nomref.most_common(5))
