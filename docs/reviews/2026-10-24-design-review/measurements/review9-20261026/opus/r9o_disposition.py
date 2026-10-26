"""Lines whose Content-Disposition appears only in a provider httpResponseHeaders list (read-only)."""
import gzip, json, os, sys, collections
from multiprocessing import Pool

def has_cd_keyed(h):
    return isinstance(h, dict) and any(isinstance(k, str) and k.lower() == "content-disposition" for k in h)

def has_cd_items(items):
    return isinstance(items, list) and any(isinstance(x, dict) and str(x.get("name", "")).lower() == "content-disposition" for x in items)

def scan(p):
    c = collections.Counter()
    with gzip.open(p, "rb") as f:
        for raw in f:
            if b"ontent-disposition" not in raw.lower() and b"ontent-Disposition" not in raw:
                continue
            o = json.loads(raw)
            rec = o.get("record")
            if not isinstance(rec, dict):
                continue
            keyed = has_cd_keyed(rec.get("response_headers")) or has_cd_items(rec.get("response_header_items")) or has_cd_keyed(rec.get("headers"))
            sm = rec.get("source_metadata") or {}
            keyed_sm = isinstance(sm, dict) and (has_cd_keyed(sm.get("response_headers")) or has_cd_items(sm.get("response_header_items")))
            prov = rec.get("provider_response") or {}
            provider = isinstance(prov, dict) and has_cd_items(prov.get("httpResponseHeaders"))
            c["lines_with_cd_anywhere"] += 1
            if provider:
                c["provider_cd"] += 1
                if not keyed and not keyed_sm:
                    c["provider_cd_only"] += 1
    return c

if __name__ == "__main__":
    root = sys.argv[1]
    files = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".jsonl.gz")]
    tot = collections.Counter()
    with Pool(10) as pool:
        for c in pool.imap_unordered(scan, files):
            tot.update(c)
    print(dict(tot))
