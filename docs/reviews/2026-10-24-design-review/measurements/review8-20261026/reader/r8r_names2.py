import duckdb
d='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/'
c=duckdb.connect()
c.sql(f"create view f as select * from '{d}document-filenames.parquet'")
q=lambda s: print(c.sql(s).fetchall())
q("""select count(*) filter (where regexp_matches(filename,'^[0-9a-f-]{16,}\\.[a-z]+$' ,'i')) hexish,
            count(*) filter (where regexp_matches(filename,'^[0-9]+(\\.[a-z]+)?$')) nums,
            count(*) from (select distinct document_id, filename from f)""")
q("select count(distinct document_id) filter (where len(nomination_wording)>0), count(distinct document_id) filter (where len(vote_id)>0), count(distinct document_id) filter (where len(witness_id)>0), count(distinct document_id) filter (where len(source_witness_name)>0) from f")
for r in c.sql("select vote_id[1], nomination_wording[1], filename from f where len(vote_id)>0 or len(nomination_wording)>0 limit 8").fetchall(): print(' ',r)
for r in c.sql("select source_url, measure_references, measure_number from f where filename='BILLS-119-1-M000312-Amdt-1.pdf' limit 4").fetchall(): print(' ',r)
q("select count(distinct document_id) filter (where len(source_page_title)>0 or len(source_link_label)>0) from f")
