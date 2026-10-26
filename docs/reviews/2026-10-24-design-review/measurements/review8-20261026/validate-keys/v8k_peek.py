import gzip,json,sys
p=sys.argv[1]; n=int(sys.argv[2])
with gzip.open(p,'rt') as f:
    for i,l in enumerate(f):
        if i>=n: break
        d=json.loads(l)
        def walk(o,pre=''):
            if isinstance(o,dict):
                for k,v in o.items(): walk(v,pre+'.'+k)
            elif isinstance(o,list):
                if o: walk(o[0],pre+'[]')
            else:
                s=repr(o)[:80]
                print(pre,s)
        walk(d); print('----')
