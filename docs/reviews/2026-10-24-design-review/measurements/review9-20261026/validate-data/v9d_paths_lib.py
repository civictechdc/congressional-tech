import gzip, json, os, re, collections
from multiprocessing import Pool
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts'
PFX=['/Users/','/home/','/private/','/tmp/','/var/folders/','/var/','/Volumes/','/opt/','/root/','/runner/','/github/','/mnt/']
NEEDLE=[p.encode() for p in PFX]
ANY=re.compile('(' + '|'.join(re.escape(p) for p in PFX) + ')')
def scan(fp):
    out=collections.Counter(); ex=collections.defaultdict(list); lines=collections.defaultdict(set)
    with gzip.open(fp,'rb') as fh:
        for ln, raw in enumerate(fh):
            if not any(n in raw for n in NEEDLE): continue
            obj=json.loads(raw)
            def walk(o,p,iskey=False):
                if isinstance(o,dict):
                    for k,v in o.items():
                        walk(k,p+'.{key}',True); walk(v,p+'.'+('<k>' if ('/' in k or len(k)>40) else k))
                elif isinstance(o,list):
                    for x in o: walk(x,p+'[]')
                elif isinstance(o,str):
                    for m in ANY.finditer(o):
                        pre=o[max(0,m.start()-1):m.start()]
                        whole = m.start()==0
                        url_ctx = (not whole) and ('://' in re.split(r'[\s"]', o[max(0,m.start()-300):m.start()])[-1]) or (pre and (pre.isalnum() or pre in '.-_%)'))
                        kind=('key' if iskey else 'value')+('_whole' if whole else ('_urlctx' if url_ctx else '_embedded'))
                        cat=m.group(1)
                        out[(cat,kind)]+=1; lines[(cat,kind)].add((fp,ln))
                        if kind.endswith('_embedded') and len(ex[(cat,kind)])<4:
                            ctx=o[max(0,m.start()-25):m.start()]
                            ctx=re.sub(r'[A-Za-z0-9]{6,}','<w>',ctx)
                            ex[(cat,kind)].append((p, ctx))
            walk(obj,'$')
    return out, ex, {k:len(v) for k,v in lines.items()}, fp
