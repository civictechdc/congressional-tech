import duckdb, glob
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect()
for name in ["documents", "state"]:
    p = f"{base}/{name}.parquet"
    rows = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchall()
    print(f"=== {name}: {len(rows)} columns ===")
    for r in rows:
        if not r[1].endswith("[]") or name == "state" or r[0] in ("body_keys","bodies","members","source_ids","filenames","document_id"):
            print(f"  {r[0]}: {r[1][:120]}")
    print("  rows:", con.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0])
rd = sorted(glob.glob(f"{base}/readings/*.parquet"))
print("=== readings files:", len(rd))
for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{rd[0]}')").fetchall():
    print(f"  {r[0]}: {r[1][:120]}")
print("  rows across all:", con.execute(f"SELECT count(*) FROM read_parquet('{base}/readings/*.parquet', union_by_name=true)").fetchone()[0])
print(con.execute(f"SELECT * FROM read_parquet('{rd[0]}') LIMIT 2").fetchall())
