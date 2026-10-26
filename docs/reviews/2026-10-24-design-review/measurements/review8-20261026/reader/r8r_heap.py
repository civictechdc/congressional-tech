import duckdb
d='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes/'
c=duckdb.connect()
c.sql(f"create view f as select * from '{d}document-filenames.parquet'")
q=lambda s: print(c.sql(s).fetchall())
q("select avg(strlen(filename)), max(strlen(filename)), quantile_cont(strlen(filename),0.9) from f")
q("""select count(distinct document_id) filter (where len(source_meeting_key)>0 or regexp_matches(source_url,'docs.house.gov/meetings/|congress.gov/[0-9]+/meeting/')) mtg,
 count(distinct document_id) filter (where len(measure_references)>0 or len(measure_number)>0) meas,
 count(distinct document_id) filter (where len(bioguide_token)>0 or len(sponsor_bioguide_id)>0 or len(member_bioguide_id)>0) bio,
 count(distinct document_id) filter (where len(committee_code)>0) cc,
 count(distinct document_id) filter (where len(source_witness_name)>0) wit,
 count(distinct document_id) filter (where len(source_page_title)>0) ptitle,
 count(distinct document_id) from f""")
q("select max(len(committee_code)), max(len(measure_references)), max(len(source_meeting_key)) from f")
