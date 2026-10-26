"""Count header names (cookie family) in name/value header items and keyed header objects, by path tail."""
import gzip, json, os, sys, collections
from multiprocessing import Pool
NAMES = {"set-cookie", "cookie", "authorization", "proxy-authorization", "set-cookie2"}

def walk(v, path, c, keys):
    if isinstance(v, dict):
        nm = v.get("name")
        if isinstance(nm, str) and nm.lower() in NAMES and "value" in v:
            c[("nv", nm.lower(), path.split(".")[-1])] += 1
        for k, x in v.items():
            if isinstance(k, str) and k.lower() in NAMES:
                c[("key", k.lower(), path.split(".")[-1])] += 1
                vals = x if isinstance(x, list) else [x]
                c[("values", k.lower(), "")] += len(vals)
            walk(x, path + "." + (k if isinstance(k, str) and len(k) < 40 else "K"), c, keys)
    elif isinstance(v, list):
        for x in v:
            walk(x, path + "[]", c, keys)

def scan(p):
    c = collections.Counter()
    with gzip.open(p, "rb") as f:
        for raw in f:
            if b"ookie" not in raw and b"uthorization" not in raw:
                continue
            walk(json.loads(raw), "$", c, None)
    return c

if __name__ == "__main__":
    root = sys.argv[1]
    files = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".jsonl.gz")]
    files.sort(key=lambda p: -os.path.getsize(p))
    tot = collections.Counter()
    with Pool(10) as pool:
        for c in pool.imap_unordered(scan, files):
            tot.update(c)
    for k, v in sorted(tot.items(), key=lambda kv: -kv[1]):
        print(v, k)
