# For each receipt shape group (family path + segment kind + filename pattern), print key structure of the first line.
import os, re, gzip, json, collections
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
def shape(k):
    parts=k.split('/'); fam=[];seg=None
    for p in parts[:-1]:
        if re.match(r'\d{4}-\d{2}-\d{2}$',p): seg='DATE'
        elif p in('undated','mixed-dates'): seg=p
        else: fam.append(p)
    pat=re.sub(r'\d{8}T\d{6}Z','TS',parts[-1]); pat=re.sub(r'(?<![0-9a-z])[0-9a-f]{12}(?![0-9a-z])','H',pat); pat=re.sub(r'\d+','N',pat); pat=re.sub(r'N(-N)+','N',pat)
    return '/'.join(fam),seg,pat
groups=collections.defaultdict(list)
for dp,dn,fn in os.walk(R):
    for f in fn:
        k=os.path.relpath(os.path.join(dp,f),R); groups[shape(k)].append(k)
def typ(v):
    return type(v).__name__
for g in sorted(groups):
    ks=sorted(groups[g]); k=ks[0]
    with gzip.open(R+k,'rt') as fh:
        line=fh.readline()
    if len(line)>5_000_000: print(g,len(ks),'HUGE first line',len(line)); 
    d=json.loads(line)
    rec=d.get('record')
    print('\n##',g,'files',len(ks),'eg',k)
    print(' top:',{a:typ(b) for a,b in d.items()})
    if isinstance(rec,dict): print(' record:',sorted(rec.keys())[:30], len(rec))
    caps=d.get('captures') or []
    if caps: print(' captures[0]:',{a:typ(b) for a,b in caps[0].items()})
    fr=d.get('file_references') or []
    if fr: print(' file_references[0]:',{a:typ(b) for a,b in fr[0].items()})
