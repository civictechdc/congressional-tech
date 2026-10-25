import duckdb, glob, sys
base = "/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs"
con = duckdb.connect()
for name in ["captures", "filenames", "documents", "state"]:
    p = f"{base}/{name}.parquet"
    print(f"=== {name} ===")
    for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{p}')").fetchall():
        print(f"  {r[0]}: {r[1]}")
    print("  rows:", con.execute(f"SELECT count(*) FROM read_parquet('{p}')").fetchone()[0])
rd = sorted(glob.glob(f"{base}/readings/*.parquet"))
print("=== readings files:", len(rd))
print("  schema of first:")
for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{rd[0]}')").fetchall():
    print(f"  {r[0]}: {r[1]}")
print("  rows across all:", con.execute(f"SELECT count(*) FROM read_parquet('{base}/readings/*.parquet', union_by_name=true)").fetchone()[0])
