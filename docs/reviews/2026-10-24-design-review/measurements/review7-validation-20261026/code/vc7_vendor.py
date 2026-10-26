import tomllib,shutil,json,os,sys,glob
P=sys.argv[1]
lock=tomllib.load(open(P+'/Cargo.lock','rb'))
pk={}
for p in lock['package']: pk.setdefault(p['name'],[]).append(p)
def find(dep):
    parts=dep.split(' '); n=parts[0]
    c=pk[n]
    if len(parts)>1: c=[p for p in c if p['version']==parts[1]]
    return c[0]
roots=['arrow-json','arrow-schema','arrow-array','flate2']
seen={}; stack=[find(r) for r in roots]
while stack:
    p=stack.pop(); k=(p['name'],p['version'])
    if k in seen: continue
    seen[k]=p
    for d in p.get('dependencies',[]): stack.append(find(d))
src=glob.glob(os.path.expanduser('~/.cargo/registry/src/index.crates.io-*'))[0]
out=P+'/vendor'; os.makedirs(out,exist_ok=True); miss=[]
for (n,v),p in seen.items():
    s=f'{src}/{n}-{v}'; d=f'{out}/{n}-{v}'
    if not os.path.isdir(s): miss.append(f'{n}-{v}'); continue
    if not os.path.exists(d): shutil.copytree(s,d,symlinks=True)
    json.dump({'files':{},'package':p.get('checksum')},open(d+'/.cargo-checksum.json','w'))
print(len(seen),'missing',miss)
