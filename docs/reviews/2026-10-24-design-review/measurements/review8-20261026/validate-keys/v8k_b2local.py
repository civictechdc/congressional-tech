import duckdb
c=duckdb.connect()
I='/Users/mikewolfd/Work/congressional-tech/.cache/congressional-tech-raw/indexes'
def q(s):
    print('>>',s.replace(I+'/','')[:200])
    for r in c.sql(s).fetchall(): print('  ',r)
# every URL column in captures: extract chamber segment of congress.gov meeting web/API URLs, case-sensitively
for col in ['context_url','pointer_json']:
    q(f"""select regexp_extract({col}, '(committee-meeting|/meeting)/(?:[0-9]+/)?([A-Za-z]+)/', 2) ch, regexp_extract({col}, '(committee-meeting|/meeting)/', 1) kind, count(*) from '{I}/captures.parquet' where regexp_matches({col}, '(committee-meeting|congress\\.gov/[0-9]+[a-z]*/meeting|congress\\.gov/meeting)/') group by all order by 3 desc limit 20""")
q(f"""select regexp_extract(source_url, 'congress\\.gov/(?:[^/]+/)*?(committee-meeting|meeting)/(?:[0-9]+[a-z-]*/)?([A-Za-z]+)/', 2) ch, count(*) from '{I}/documents.parquet' where regexp_matches(source_url,'congress\\.gov.*meeting/') group by all order by 2 desc limit 20""")
q(f"select u, count(*) from (select unnest(source_chamber) u from '{I}/document-filenames.parquet') group by 1 order by 2 desc")
q(f"select family, count(*) from '{I}/captures.parquet' where family ilike '%meeting%' or family ilike '%house%' group by 1 order by 2 desc limit 30")
q(f"select context_url from '{I}/captures.parquet' where family='congress/meetings' limit 3")
q(f"select pointer_json from '{I}/captures.parquet' where family='congress/meetings' limit 2")
