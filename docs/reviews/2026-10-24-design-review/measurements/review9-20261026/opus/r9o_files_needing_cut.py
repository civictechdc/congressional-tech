"""Per receipt file: does any line hold a Set-Cookie (any form) or an absolute local path (value or key)? (read-only)"""
import gzip, json, os, sys, re
from multiprocessing import Pool
ROOTS = ("/Users/", "/home/", "/private/", "/tmp/", "/var/folders/", "/Volumes/", "/root/", "/opt/", "/mnt/", "/runner/", "/github/")
EMBED = re.compile(r"(?:/Users/|/home/runner/|/private/var/|/private/tmp/|/var/folders/|file://)")

def walk(v):
    if isinstance(v, dict):
        nm = v.get("name")
        if isinstance(nm, str) and nm.lower() == "set-cookie":
            return True
        for k, x in v.items():
            if isinstance(k, str) and (k.lower() == "set-cookie" or k.startswith(ROOTS)):
                return True
            if walk(x):
                return True
    elif isinstance(v, list):
        return any(walk(x) for x in v)
    elif isinstance(v, str):
        return v.startswith(ROOTS) or v.startswith("file://") or bool(EMBED.search(v))
    return False

def scan(p):
    size = os.path.getsize(p)
    with gzip.open(p, "rb") as f:
        for raw in f:
            low = raw.lower()
            if b"set-cookie" in low or any(r.encode() in raw for r in ROOTS) or b"file://" in raw:
                if walk(json.loads(raw)):
                    return (p, True, size)
    return (p, False, size)

if __name__ == "__main__":
    root = sys.argv[1]
    files = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".jsonl.gz")]
    files.sort(key=lambda p: -os.path.getsize(p))
    need = clean = 0; need_b = clean_b = 0
    with Pool(10) as pool:
        for p, n, s in pool.imap_unordered(scan, files):
            if n: need += 1; need_b += s
            else: clean += 1; clean_b += s
    print(f"receipts needing a cut: {need} ({need_b/1e6:.0f} MB); with nothing to cut: {clean} ({clean_b/1e6:.0f} MB)")
