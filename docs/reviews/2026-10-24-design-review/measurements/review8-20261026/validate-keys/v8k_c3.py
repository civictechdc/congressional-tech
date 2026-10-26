import duckdb
c=duckdb.connect()
I='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes'
def q(s,lim=15):
    print('>>',s[:300].replace(I+'/',''))
    for r in c.sql(s).fetchall()[:lim]: print('  ',r)
c.sql(f"create view d as select * from '{I}/documents.parquet' where regexp_matches(source_url,'^https?://[^/]*senate\\.gov/')")
q("select count(*) from d")
q("select count(*) filter (where regexp_matches(lower(filename),'testimony|statement|_test|-test|testimon')) t, count(*) filter (where len(source_witness_name)>0) w, count(*) filter (where len(source_participant_label)>0) pl, count(*) filter (where len(source_document_group)>0) g, count(*) filter (where len(witness_id)>0) wid from d")
q("select x, count(*) from (select unnest(source_association_basis) x from d) group by 1 order by 2 desc")
q("select x, count(*) from (select unnest(document_kind) x from d) group by 1 order by 2 desc",12)
q("select x, count(*) from (select unnest(source_page_type) x from d) group by 1 order by 2 desc",12)
q("select x, count(*) from (select unnest(source_document_group) x from d) group by 1 order by 2 desc",12)
q("select filename, source_witness_name, source_link_label, source_link_heading, source_page_url from d where len(source_witness_name)>0 using sample 6 rows")
