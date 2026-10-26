import gzip,json,sys,glob,collections
R=sys.argv[1]; c=collections.Counter(); ev=collections.defaultdict(lambda:[0,0,0])
for p in glob.glob(R+'/congress/meetings/**/*.jsonl.gz',recursive=True):
    for l in gzip.open(p,'rt'):
        r=json.loads(l).get('record') or {}
        if not isinstance(r,dict) or 'eventId' not in r: continue
        e=ev[(r.get('chamber'),str(r['eventId']))]
        e[0]=1; e[1]|=bool(r.get('witnesses')); e[2]|=bool(r.get('witnessDocuments'))
for (ch,_),v in ev.items(): c[(ch,'events')]+=1; c[(ch,'with_witnesses')]+=v[1]; c[(ch,'with_witness_docs')]+=v[2]
for k in sorted(c, key=str): print(k,c[k])
