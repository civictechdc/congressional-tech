import gzip, json, sys, glob, re
R='/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/'
needle=sys.argv[1]; n=int(sys.argv[2]); maxfiles=int(sys.argv[3]) if len(sys.argv)>3 else 10**9
red=re.compile(r'((?:api_key|token|key|sig|signature|auth)[^=&"]{0,10}=)[^&"\s]+',re.I)
found=0
for i,p in enumerate(sorted(glob.glob(R+'**/*.gz',recursive=True))):
    if i>=maxfiles: break
    with gzip.open(p,'rt') as f:
        for j,l in enumerate(f):
            if needle in l:
                print(p.replace(R,''),j, red.sub(r'\1R', l[:3000])); found+=1
                if found>=n: sys.exit()
