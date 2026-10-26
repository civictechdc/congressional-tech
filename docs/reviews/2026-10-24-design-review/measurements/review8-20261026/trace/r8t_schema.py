import duckdb, sys
base="/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/"
con=duckdb.connect()
for f in ["captures","documents","document-filenames","download-state"]:
    p=base+f+".parquet"
    print("==",f)
    for r in con.execute(f"describe select * from read_parquet('{p}')").fetchall():
        print("  ",r[0],r[1])
    print("  rows:",con.execute(f"select count(*) from read_parquet('{p}')").fetchone()[0])
