"""Shared duckdb views over the scan output and the snapshot tables."""
import duckdb, os
HERE=os.path.dirname(os.path.abspath(__file__))
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
def con():
    c=duckdb.connect()
    c.execute("set TimeZone='UTC'")
    c.execute(f"create view l as select * from read_parquet('{HERE}/scan/lines/*.parquet', union_by_name=true)")
    c.execute(f"create view r as select * from read_parquet('{HERE}/scan/refs/*.parquet', union_by_name=true)")
    c.execute(f"create view c as select * from read_parquet('{A}captures.parquet')")
    c.execute(f"create view f as select * from read_parquet('{A}filenames.parquet')")
    c.execute(f"create view d as select * from read_parquet('{A}documents.parquet')")
    return c
def q(c, s, label=None):
    print('##', label or s)
    rows=c.execute(s).fetchall()
    for x in rows: print('  ', x)
    return rows
