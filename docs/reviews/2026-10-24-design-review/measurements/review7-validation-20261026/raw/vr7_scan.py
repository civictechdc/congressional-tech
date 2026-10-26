"""One streaming pass over all 2,289 raw receipts (read-only).

Writes, under scan/ beside this script:
  lines/<n>.parquet  one row per receipt line (fetch fields, time fields, header facts, counts)
  refs/<n>.parquet   one row per body reference: captures[] entries (kind='cap') and
                     file_references[] entries (kind='fref')
  types/<n>.json     per receipt: JSON type counts per normalized path (list index -> [],
                     dicts with >64 keys -> *), plus per-path line counts
Values that may be credentials (cookies, tokens) are never extracted: only URLs, times,
statuses, sizes, hashes, media types and header names/lengths/dates.
"""
import collections, gzip, json, os, re, sys
from concurrent.futures import ProcessPoolExecutor
import pyarrow as pa, pyarrow.parquet as pq

ROOT = "/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan")
SCAL = re.compile(r"(_at$|status|url$|^outcome$|^result$|^mode$|^usable$|complete$|^transport$|^error$)")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def jt(v):
    if v is None: return "null"
    if isinstance(v, bool): return "bool"
    if isinstance(v, int): return "int"
    if isinstance(v, float): return "float"
    if isinstance(v, str): return "str"
    if isinstance(v, list): return "list"
    return "obj"


def walk(v, path, acc):
    t = jt(v)
    acc[(path, t)] += 1
    if t == "obj":
        star = len(v) > 64
        for k, x in v.items():
            walk(x, path + "." + ("*" if star else k), acc)
    elif t == "list":
        for x in v:
            walk(x, path + "[]", acc)


def s(v):
    if v is None: return None
    if isinstance(v, str): return v
    return json.dumps(v)


def hdr_get(h, name):
    """Header value from a dict or a list of pairs/objects, case-insensitive."""
    if isinstance(h, dict):
        for k, v in h.items():
            if isinstance(k, str) and k.lower() == name:
                return v
    elif isinstance(h, list):
        for it in h:
            if isinstance(it, (list, tuple)) and len(it) >= 2 and isinstance(it[0], str) and it[0].lower() == name:
                return it[1]
            if isinstance(it, dict):
                k = it.get("name") or it.get("key")
                if isinstance(k, str) and k.lower() == name:
                    return it.get("value")
    return None


def times(rec):
    out = {}
    if isinstance(rec, dict):
        for k, v in rec.items():
            if isinstance(k, str) and k.endswith("_at") and isinstance(v, str):
                out[k] = v
        sub = rec.get("receipt")
        if isinstance(sub, dict):
            for k, v in sub.items():
                if isinstance(k, str) and k.endswith("_at") and isinstance(v, str):
                    out["receipt." + k] = v
    return json.dumps(out, sort_keys=True) if out else None


def scan(idx_rel):
    idx, rel = idx_rel
    parts = rel.split("/")
    dated = any(DATE.match(p) for p in parts[:-1])
    seg = "DATE" if dated else ("mixed-dates" if "mixed-dates" in parts else "undated")
    L = collections.defaultdict(list)
    R = collections.defaultdict(list)
    types = collections.Counter()
    pathlines = collections.Counter()
    with gzip.open(ROOT + rel, "rb") as fh:
        for ln, raw in enumerate(fh, 1):
            d = json.loads(raw)
            acc = collections.Counter()
            walk(d, "$", acc)
            types.update(acc)
            for (p, t) in acc:
                pathlines[(p, t)] += 1
            rec = d.get("record")
            r = rec if isinstance(rec, dict) else {}
            hs = r.get("response_headers")
            hi = r.get("response_header_items")
            hh = r.get("headers")
            caps = d.get("captures") if isinstance(d.get("captures"), list) else []
            frs = d.get("file_references") if isinstance(d.get("file_references"), list) else []
            L["rk"].append(rel); L["ln"].append(ln); L["seg"].append(seg); L["nbytes"].append(len(raw))
            L["source_line"].append(d.get("source_line") if isinstance(d.get("source_line"), int) else None)
            L["top_keys"].append(",".join(sorted(d.keys())))
            L["rec_type"].append(jt(rec)); L["rec_nkeys"].append(len(rec) if isinstance(rec, (dict, list)) else None)
            for f in ("mode", "outcome", "result", "transport", "requested_url", "url", "final_url", "_url",
                      "request_url", "original_url", "publisher_url", "resolved_url", "detail_url", "master_url",
                      "segment_url", "playlist_url"):
                L["r_" + (f if not f.startswith("_") else "x" + f)].append(s(r.get(f)) if f in r else None)
            for f in ("http_status", "status", "provider_http_status", "complete", "body_complete", "usable"):
                v = r.get(f, "<absent>")
                L["r_" + f].append(None if v == "<absent>" else jt(v) + ":" + (s(v) or ""))
            L["has_recovery_evidence"].append("recovery_evidence" in r)
            L["publisher_requested"].append(s(r.get("publisher_requested")) if "publisher_requested" in r else None)
            L["times"].append(times(rec))
            L["hdr_headers_kind"].append(jt(hh) if hh is not None else None)
            sc = {k: v for k, v in r.items() if isinstance(k, str) and SCAL.search(k)
                  and (v is None or isinstance(v, (str, int, float, bool))) and not (isinstance(v, str) and len(v) > 2000)}
            L["rec_scalars"].append(json.dumps(sc, sort_keys=True) if sc else None)
            L["hdr_kind"].append(jt(hs) if hs is not None else None)
            L["hdr_items_kind"].append(jt(hi) if hi is not None else None)
            for name in ("date", "content-length", "content-encoding", "transfer-encoding", "content-type"):
                v = hdr_get(hs, name)
                if v is None:
                    v = hdr_get(hi, name)
                if v is None:
                    v = hdr_get(hh, name)
                L["h_" + name.replace("-", "_")].append(s(v)[:200] if v is not None else None)
            L["n_caps"].append(len(caps)); L["n_frefs"].append(len(frs))
            L["n_prior"].append(len(r.get("prior_attempts")) if isinstance(r.get("prior_attempts"), list) else None)
            for kind, arr in (("cap", caps), ("fref", frs)):
                for i, c in enumerate(arr):
                    if not isinstance(c, dict):
                        c = {"_nondict": jt(c)}
                    p = c.get("pointer")
                    op = c.get("original_path")
                    R["rk"].append(rel); R["ln"].append(ln); R["kind"].append(kind); R["i"].append(i)
                    R["sha256"].append(c.get("sha256") if isinstance(c.get("sha256"), str) else None)
                    b = c.get("bytes")
                    R["bytes_type"].append(jt(b))
                    try:
                        R["bytes"].append(int(b) if b is not None and not isinstance(b, bool) else None)
                    except (ValueError, TypeError):
                        R["bytes"].append(None)
                    sb = c.get("stored_bytes")
                    R["stored_bytes"].append(sb if isinstance(sb, int) and not isinstance(sb, bool) else None)
                    R["body_key"].append(c.get("body_key") if isinstance(c.get("body_key"), str) else None)
                    for f in ("media_type", "fidelity", "retrieved_at", "capture_date", "reference_kind",
                              "resolution", "context_url", "status", "string_encoding", "family",
                              "captured_at", "status_code", "observed_at", "checked_at"):
                        R[f].append(s(c.get(f)))
                    hv = c.get("http_status", "<absent>")
                    R["http_status"].append(None if hv == "<absent>" else jt(hv) + ":" + (s(hv) or ""))
                    R["has_original_path"].append(op is not None)
                    R["original_path_abs"].append(isinstance(op, str) and op.startswith("/"))
                    R["original_path_tail"].append(op.rsplit("/", 1)[-1][:300] if isinstance(op, str) else None)
                    R["pointer"].append(json.dumps(p)[:300] if p is not None else c.get("pointer_json"))
                    R["ptr_types"].append(",".join(sorted({jt(e) for e in p})) if isinstance(p, list) else jt(p))
                    R["entry_keys"].append(",".join(sorted(c.keys())))
    os.makedirs(OUT + "/lines", exist_ok=True); os.makedirs(OUT + "/refs", exist_ok=True)
    os.makedirs(OUT + "/types", exist_ok=True)
    pq.write_table(pa.table(dict(L)), f"{OUT}/lines/{idx:05d}.parquet")
    if R:
        pq.write_table(pa.table(dict(R)), f"{OUT}/refs/{idx:05d}.parquet")
    json.dump({"rk": rel, "types": [[p, t, n, pathlines[(p, t)]] for (p, t), n in types.items()]},
              open(f"{OUT}/types/{idx:05d}.json", "w"))
    return rel, len(L["rk"])


def main():
    rels = []
    for dp, _, fs in os.walk(ROOT):
        for f in fs:
            rels.append(os.path.relpath(os.path.join(dp, f), ROOT))
    rels.sort()
    order = sorted(range(len(rels)), key=lambda i: -os.path.getsize(ROOT + rels[i]))
    tot = 0
    with ProcessPoolExecutor(max_workers=10) as ex:
        for rel, n in ex.map(scan, [(i, rels[i]) for i in order]):
            tot += n
    print("files", len(rels), "lines", tot)


if __name__ == "__main__":
    main()
