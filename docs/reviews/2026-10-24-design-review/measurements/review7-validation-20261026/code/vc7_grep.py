import sys,re,os
# usage: vc7_grep.py PATTERN path... [-C n]
ctx=0
args=sys.argv[1:]
if '-C' in args:
    i=args.index('-C'); ctx=int(args[i+1]); del args[i:i+2]
pat=re.compile(args[0]); paths=args[1:]
def scan(p):
    try: lines=open(p,errors='replace').read().split('\n')
    except Exception: return
    for i,l in enumerate(lines):
        if pat.search(l):
            lo=max(0,i-ctx); hi=min(len(lines),i+ctx+1)
            for j in range(lo,hi): print(f"{p}:{j+1}:{lines[j][:300]}")
            if ctx: print('--')
for p in paths:
    if os.path.isdir(p):
        for r,ds,fs in os.walk(p):
            ds[:]=[d for d in ds if d not in('target','.git','node_modules')]
            for f in fs:
                if f.endswith(('.rs','.py','.js','.ts','.md','.toml','.json')): scan(os.path.join(r,f))
    else: scan(p)
