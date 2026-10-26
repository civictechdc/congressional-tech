"""HEAD older bodies on both public hosts and record ETag forms (read-only, <=4 req/s).

Usage: vr7_etags.py sample   -> the reviewer's exact key, its 20 sampled keys, and a seeded
                                 random 40 of older bodies over 100 MiB (snapshot sizes)
       vr7_etags.py all      -> every older body over 100 MiB (snapshot sizes), r2.dev host
Writes etags_<mode>.json beside this script.
"""
import json, os, random, sys, time, urllib.request
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
C = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/captures.parquet"
HOSTS = {"r2dev": "https://pub-1b36ca710ab14e7f8e65813c41761724.r2.dev/",
         "custom": "https://congressional-data.spicygov.ai/"}
UA = "congressional-tech-review/1.0"
MIB100 = 100 * 1024 * 1024
EXACT = "bodies/sha256/29/29594f8d69942ae1b15155030cf0febf3b9a69397fb16c27aad029e186e4879d.gz"
_last = [0.0]


def head(url):
    wait = 0.25 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            h = r.headers
            return {"status": r.status, "etag": h.get("ETag"), "length": h.get("Content-Length"),
                    "last_modified": h.get("Last-Modified"), "content_type": h.get("Content-Type"),
                    "content_encoding": h.get("Content-Encoding"), "cf_cache": h.get("cf-cache-status")}
    except urllib.error.HTTPError as e:
        return {"status": e.code}
    except Exception as e:  # network error
        return {"status": None, "error": type(e).__name__}


def population():
    con = duckdb.connect()
    rows = con.execute(f"""
        select sha256, max(bytes) b, max(stored_bytes) sb, min(retrieved_at) t0,
               min(receipt_key) rk, min(capture_date) cd
        from read_parquet('{C}') where sha256 is not null
        group by sha256 having max(bytes) > {MIB100} order by sha256""").fetchall()
    return [dict(zip(["sha256", "bytes", "stored_bytes", "first_retrieved_at", "receipt_key", "capture_date"], r))
            for r in rows]


def key(sha):
    return f"bodies/sha256/{sha[:2]}/{sha}.gz"


def main():
    mode = sys.argv[1]
    pop = population()
    by = {p["sha256"]: p for p in pop}
    print("population over 100 MiB (original bytes):", len(pop))
    out = {"population_over_100MiB_original": len(pop), "results": []}
    if mode == "sample":
        rev = json.load(open(os.path.join(HERE, "..", "iceberg", "ice7_out", "etags.json")))
        rev_keys = [r["key"] for r in rev["results"]]
        rnd = random.Random(20261026)
        sample = [key(p["sha256"]) for p in rnd.sample(pop, 40)]
        targets = [("exact", EXACT)] + [("reviewer", k) for k in rev_keys if k != EXACT] + [("seeded40", k) for k in sample]
        hosts = list(HOSTS)
    else:
        targets = [("all", key(p["sha256"])) for p in pop]
        hosts = ["r2dev"]
    for grp, k in targets:
        sha = k.split("/")[-1].split(".")[0]
        row = {"group": grp, "key": k, "snapshot": by.get(sha)}
        for h in hosts:
            row[h] = head(HOSTS[h] + k)
        out["results"].append(row)
    json.dump(out, open(os.path.join(HERE, f"etags_{mode}.json"), "w"), indent=1, default=str)
    for h in hosts:
        n = sum(1 for r in out["results"] if r[h].get("status") == 200)
        m = sum(1 for r in out["results"] if (r[h].get("etag") or "").find("-") >= 0)
        print(h, "200s", n, "multipart", m, "of", len(out["results"]))


if __name__ == "__main__":
    main()
