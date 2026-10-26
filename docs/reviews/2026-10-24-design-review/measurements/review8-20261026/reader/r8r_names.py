import duckdb
d='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/'
c=duckdb.connect()
c.sql(f"create view f as select * from '{d}document-filenames.parquet'")
q=lambda s: print(c.sql(s).fetchall())
q("select count(*), count(distinct filename), count(distinct document_id) from f")
print('top filenames by docs'); 
for r in c.sql("select filename, count(distinct document_id) n from f group by 1 order by 2 desc limit 25").fetchall(): print('  ',r)
q("""select count(*) filter (where regexp_matches(filename,'^[0-9a-f-]{16,}\\.[a-z]+$' ,'i')) hexish,
            count(*) filter (where regexp_matches(filename,'^[0-9]+\\.[a-z]+$')) numeric,
            count(*) from (select distinct document_id, filename from f)""")
q("select count(distinct document_id) filter (where len(nomination_wording)>0), count(distinct document_id) filter (where len(vote_id)>0), count(distinct document_id) filter (where len(witness_id)>0), count(distinct document_id) filter (where len(source_witness_name)>0) from f")
q("select vote_id[1], nomination_wording[1], filename from f where len(vote_id)>0 or len(nomination_wording)>0 limit 8")
