import duckdb
C='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/captures.parquet'
con=duckdb.connect()
con.execute(f"create view c as select * from read_parquet('{C}')")
def q(s):
    print('##',s); 
    for r in con.execute(s).fetchall(): print('  ',r)
q("select reference_kind, count(*), count(sha256), count(retrieved_at), count(http_status), count(original_path) from c group by 1 order by 2 desc")
q("select resolution, count(*) from c group by 1 order by 2 desc")
q("select fidelity, count(*) from c group by 1 order by 2 desc")
q("select count(distinct receipt_key), count(distinct (receipt_key,receipt_line)), max(receipt_key) from c")
q("select substr(pointer_json,1,40) p, count(*) from c group by 1 order by 2 desc limit 15")
q("select capture_date='undated', count(*) from c group by 1")
q("select reference_kind, sha256 is null, count(*) from c group by 1,2 order by 3 desc")
q("select max(receipt_key) from c where receipt_key like 'documents/2026-10-1%'")
