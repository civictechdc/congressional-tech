"""Lines that do not round-trip byte-for-byte, and whether each also needs a cut (read-only). Self-contained for python -I."""
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
    n = cut = 0
    with gzip.open(p, "rb") as f:
        for raw in f:
            line = raw.rstrip(b"\n")
            if b"\\u" not in line:
                continue
            o = json.loads(line)
            if json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode() != line:
                n += 1
                cut += bool(walk(o))
    return n, cut

if __name__ == "__main__":
    root = sys.argv[1]
    files = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".jsonl.gz")]
    tn = tc = 0
    with Pool(10) as pool:
        for n, c in pool.imap_unordered(scan, files):
            tn += n; tc += c
    print("non-round-tripping lines:", tn, "of which also need a cut:", tc)
