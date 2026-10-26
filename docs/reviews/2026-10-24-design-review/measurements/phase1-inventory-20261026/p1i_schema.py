import sys, pyarrow.parquet as pq
for p in sys.argv[1:]:
    f = pq.ParquetFile(p)
    print("==", p, f.metadata.num_rows, "rows")
    md = f.schema_arrow.metadata or {}
    for k,v in md.items():
        print("  meta", k[:60], v[:300])
    for fld in f.schema_arrow:
        print("  ", fld.name, fld.type)
