import duckdb
A='/Users/mikewolfd/Work/congressional-tech/output/incremental-updates-20261019/adoption-inputs/'
con=duckdb.connect('/private/tmp/claude-501/-Users-mikewolfd-Work/71969fc5-4a0f-4f4e-aa49-d2dd9f4c2272/scratchpad/phase1-inventory/p1i.duckdb'); con.execute("SET threads=4; SET memory_limit='8GB'")
q=lambda s: con.execute(s).fetchall()
con.execute(f"create or replace table rd as select * from read_parquet('{A}readings/*.parquet', union_by_name=true)")
print("rows/bodies", q("select count(*), count(distinct body_key) from rd"))
print("fp", q("select parser_fingerprint, count(*) from rd group by 1 order by 2 desc limit 8"))
print("status", q("select status, error_type, count(*) from rd group by 1,2 order by 3 desc limit 12"))
print("bf", q("select body_format, count(*) from rd group by 1 order by 2 desc limit 12"))
print("srt", q("select source_record_type, count(*) from rd group by 1 order by 2 desc limit 12"))
print("kind", q("select content_document_kind, count(*) from rd group by 1 order by 2 desc limit 12"))
print("xmlroot", q("select content_xml_root, count(*) from rd group by 1 order by 2 desc limit 5"))
print("srdu", q("select count(*) filter (where len(source_record_document_url)>0) from rd"))
