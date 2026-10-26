import duckdb
c=duckdb.connect()
I='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes'
def q(s,lim=40):
    print('>>',s[:200].replace(I+'/',''))
    for r in c.sql(s).fetchall()[:lim]: print('  ',r)
c.sql(f"""create table d as select *, regexp_extract(source_url,'^https?://(?:www\\.)?([^/]*senate\\.gov)/',1) host,
  list_has_any(document_kind,['testimony','witness-statement','statement','questions-for-record-response']) kindt,
  regexp_matches(lower(filename),'testimony|testimon|statement|_test[._ -]|qfr') namet
  from '{I}/documents.parquet' where regexp_matches(source_url,'^https?://[^/]*senate\\.gov/')""")
q("select count(*) filter (where kindt), count(*) filter (where namet), count(*) filter (where kindt or namet) from d")
q("""select (kindt or namet) t, len(source_participant_label)>0 card, len(source_witness_name)>0 wn, count(*) from d group by all order by all""")
q("""select host, count(*) filter (where kindt or namet) t, count(*) filter (where (kindt or namet) and len(source_participant_label)>0) card, round(100.0*card/t,1) pct from d group by 1 having t>100 order by t desc""")
