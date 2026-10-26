import os, collections, re, sys
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
files=[]
for dp,dn,fn in os.walk(R):
    for f in fn:
        p=os.path.join(dp,f); files.append((os.path.relpath(p,R), os.path.getsize(p)))
print('files',len(files),'bytes',sum(s for _,s in files))
c=collections.Counter(); b=collections.Counter()
for k,s in files:
    parts=k.split('/')
    seg=parts[1] if re.match(r'\d{4}-\d{2}-\d{2}$',parts[1]) is None else 'DATE'
    pat=re.sub(r'[0-9a-f]{8,}','H',re.sub(r'\d+','N',parts[-1]))
    c[(parts[0],seg)]+=1; b[(parts[0],seg)]+=s
for k in sorted(c): print(k,c[k],b[k])
ext=collections.Counter(os.path.splitext(k)[1] for k,_ in files); print(ext)
files.sort(key=lambda x:-x[1]); print(files[:10])
