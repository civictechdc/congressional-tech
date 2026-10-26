import os, re, collections, sys
root = sys.argv[1]
c = collections.Counter()
sizes = collections.Counter()
for dp, dn, fn in os.walk(root):
    for f in fn:
        p = os.path.join(dp, f)
        rel = os.path.relpath(p, root)
        parts = rel.split('/')
        seg = parts[-2]
        segkind = 'date' if re.fullmatch(r'\d{4}-\d{2}-\d{2}', seg) else seg
        fam = '/'.join(parts[:-2])
        run = re.sub(r'\d{8}(-\d{6})?', 'D', f)
        run = re.sub(r'-\d+\.jsonl\.gz$', '-N.jsonl.gz', run)
        run = re.sub(r'\d+', 'n', run)
        c[(fam, segkind, run)] += 1
        sizes[(fam, segkind, run)] += os.path.getsize(p)
for k, v in sorted(c.items(), key=lambda kv: -sizes[kv[0]]):
    print(f"{v:5d} {sizes[k]/1e6:9.1f}MB  {k[0]:28s} {k[1]:12s} {k[2]}")
