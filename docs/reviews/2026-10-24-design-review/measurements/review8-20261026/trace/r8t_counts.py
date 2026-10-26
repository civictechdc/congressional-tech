import duckdb, gzip, json, os
base="/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/"
con=duckdb.connect(); q=lambda s: con.execute(s).fetchall()
c=f"read_parquet('{base}captures.parquet')"
print("placeholders k=100:", q(f"select count(*), max(n) from (select sha256, count(distinct context_url) n from {c} where sha256 is not null group by 1) where n>100"))
print("placeholders k=50 / k=200:", q(f"select count(*) filter (where n>50), count(*) filter (where n>200) from (select sha256, count(distinct context_url) n from {c} where sha256 is not null group by 1)"))
print("recovery bodies also on a fetched 2xx row:", q(f"select count(distinct r.sha256), count(distinct r.sha256) filter (where exists (select 1 from {c} f where f.sha256=r.sha256 and f.reference_kind<>'retained-file' and f.http_status between 200 and 299)) from {c} r where r.reference_kind='retained-file' and r.sha256 is not null"))
root="/Users/mikewolfd/Work/congressional-tech/.cache/docspec-catalog/r2-immutable/receipts/"
pr=0; n=0
for dp,_,fs in os.walk(root):
    for f in fs:
        op=gzip.open if f.endswith(".gz") else open
        with op(os.path.join(dp,f),"rt",encoding="utf-8",errors="replace") as fh:
            for line in fh:
                try: o=json.loads(line)
                except Exception: continue
                if not isinstance(o,dict): continue
                rec=o.get("record",o); src=rec if "recovery_evidence" in rec else (o if "recovery_evidence" in o else None)
                if src is None: continue
                n+=1; pr+= 1 if src.get("publisher_requested") is True else 0
print("import lines:",n,"publisher_requested true:",pr)
