"""Do receipt lines survive json.loads -> json.dumps(ensure_ascii=False, separators=(',',':')) byte-for-byte? (read-only)"""
import gzip, json, os, sys, collections
from multiprocessing import Pool

def scan(p):
    c = collections.Counter()
    ex = None
    with gzip.open(p, "rb") as f:
        for raw in f:
            line = raw.rstrip(b"\n")
            c["lines"] += 1
            try:
                again = json.dumps(json.loads(line), ensure_ascii=False, separators=(",", ":")).encode()
            except Exception:
                c["unparseable"] += 1
                continue
            if again != line:
                c["differs"] += 1
                if ex is None:
                    i = next((k for k in range(min(len(line), len(again))) if line[k] != again[k]), min(len(line), len(again)))
                    ex = (os.path.basename(p), line[max(0, i-40):i+40].decode("utf-8", "replace"), again[max(0, i-40):i+40].decode("utf-8", "replace"))
    return c, ex, p

if __name__ == "__main__":
    root = sys.argv[1]
    files = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".jsonl.gz")]
    files.sort(key=lambda p: -os.path.getsize(p))
    tot = collections.Counter(); exs = []; fam = collections.Counter()
    with Pool(10) as pool:
        for c, ex, p in pool.imap_unordered(scan, files):
            tot.update(c)
            if c["differs"]:
                fam[os.path.relpath(p, root).split("/")[0]] += c["differs"]
            if ex and len(exs) < 4:
                exs.append(ex)
    print(dict(tot)); print("differing lines by family:", dict(fam))
    for e in exs:
        print(e)
