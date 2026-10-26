import gzip,json,glob,collections as C,time,sys
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
ctx=C.defaultdict(set); size={}; t0=time.time(); src=C.Counter()
for p in sorted(glob.glob(R+'**/*.gz',recursive=True)):
    with gzip.open(p,'rt') as f:
        for l in f:
            o=json.loads(l); r=o.get('record'); r=r if isinstance(r,dict) else {}
            lu=o.get('url') or r.get('url') or r.get('final_url') or r.get('_url') or r.get('requested_url') or o.get('requested_url')
            rows=(o.get('captures') or []) or (o.get('file_references') or [])
            for e in rows:
                if not isinstance(e,dict): continue
                s=e.get('sha256')
                if not s: continue
                s=s[-64:]
                cu=e.get('context_url')
                if cu: src['entry']+=1
                else:
                    cu=lu; src['line' if lu else 'none']+=1
                if cu is None: continue
                ctx[s].add(hash(cu)); size[s]=e.get('bytes')
print('elapsed',time.time()-t0,'bodies',len(ctx),src,file=sys.stderr)
n=sorted(((len(v),k) for k,v in ctx.items()),reverse=True)
for k in (50,100,200): print('k',k,'bodies >k',sum(1 for x,_ in n if x>k))
print('widest',n[0][0],size[n[0][1]],'bytes')
print('top 25 widths',[x for x,_ in n[:25]])
