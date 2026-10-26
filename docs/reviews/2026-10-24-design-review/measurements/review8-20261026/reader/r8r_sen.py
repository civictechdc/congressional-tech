import duckdb
d='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/'
c=duckdb.connect()
c.sql(f"create view f as select * from '{d}document-filenames.parquet'")
for r in c.sql("""select regexp_extract(source_url,'https?://([^/]+)/',1) host, count(distinct document_id) from f where len(source_witness_name)>0 group by 1 order by 2 desc limit 8""").fetchall(): print(r)
for r in c.sql("""select count(distinct document_id) from f where regexp_matches(source_url,'senate\\.gov') and (regexp_matches(lower(filename),'testimony|statement') )""").fetchall(): print('senate testimony-like docs',r)
