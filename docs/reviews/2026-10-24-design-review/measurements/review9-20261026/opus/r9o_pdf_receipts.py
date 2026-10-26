"""Cross-check from raw receipts (not the index): PDF bodies whose line outcome is saved/invalid_document
on receipts dated 2026-10-01 or later, by receipt date bucket. Writes a sha256 list per bucket."""
import gzip, json, os, re, sys, collections
from multiprocessing import Pool

def scan(p):
    m = re.search(r"/(\d{4}-\d{2}-\d{2})/", p)
    d = m.group(1) if m else None
    if not d or d < "2026-10-01":
        return None
    out = collections.defaultdict(set)
    with gzip.open(p, "rb") as f:
        for raw in f:
            if b"pdf" not in raw:
                continue
            o = json.loads(raw)
            rec = o.get("record") if isinstance(o.get("record"), dict) else {}
            outcome = rec.get("outcome")
            for e in o.get("captures") or []:
                if not isinstance(e, dict):
                    continue
                mt = (e.get("media_type") or "").lower()
                if "pdf" not in mt or not e.get("sha256"):
                    continue
                ptr = e.get("pointer") or []
                final = ptr[:1] == ["content"]
                out[(d == "2026-10-01", outcome, final)].add(e["sha256"])
    return {k: sorted(v) for k, v in out.items()}

if __name__ == "__main__":
    root = sys.argv[1]
    files = [os.path.join(dp, f) for dp, _, fs in os.walk(root) for f in fs if f.endswith(".jsonl.gz")]
    agg = collections.defaultdict(set)
    with Pool(10) as pool:
        for r in pool.imap_unordered(scan, files):
            if r:
                for k, v in r.items():
                    agg[k].update(v)
    for k in sorted(agg, key=str):
        print(k, len(agg[k]))
    allchk = set().union(*[v for (on1001, oc, fin), v in agg.items() if oc in ("saved", "invalid_document")])
    later = set().union(*[v for (on1001, oc, fin), v in agg.items() if oc in ("saved", "invalid_document") and not on1001])
    print("bodies with saved|invalid_document on >=2026-10-01 lines:", len(allchk))
    print("  of which only on 2026-10-01 lines:", len(allchk - later))
    inv = set().union(*[v for (on1001, oc, fin), v in agg.items() if oc == "invalid_document"] or [set()])
    print("bodies with invalid_document:", len(inv))
    with open(sys.argv[2], "w") as f:
        json.dump(sorted(allchk), f)
