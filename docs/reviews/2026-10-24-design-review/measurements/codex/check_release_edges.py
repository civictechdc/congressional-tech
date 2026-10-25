from pathlib import Path
import json
import duckdb
con=duckdb.connect('review.duckdb')
con.execute("SET threads=4")
con.execute("SET memory_limit='3GB'")
con.execute("SET temp_directory='./duckdb_tmp'")
out={}
def q(label,sql):
    cur=con.execute(sql)
    cols=[x[0] for x in cur.description]
    out[label]=[dict(zip(cols,row)) for row in cur.fetchall()]
    print(label,json.dumps(out[label],default=str),flush=True)
    Path('release_edge_measurements.json').write_text(json.dumps(out,indent=2,default=str))
q('member_html_format', '''SELECT count(*) n,count(distinct c.sha256) bodies,
 count(*) FILTER(WHERE c.http_status between 200 and 299) status_2xx,
 count(*) FILTER(WHERE regexp_matches(c.context_url,'(?i)\\.zip([?#]|$)')) zip_context
 FROM c JOIN r USING(body_key) WHERE contains(c.pointer_json,'archive_members')
 AND list_contains(r.body_format,'html')''')
q('raw_filename_gaps', '''SELECT count(*) n,
 count(*) FILTER(WHERE filename IS NULL) filename_null,
 count(*) FILTER(WHERE filename IS NULL AND body_key IS NOT NULL) null_name_body,
 count(*) FILTER(WHERE source_url IS NULL AND body_key IS NOT NULL) null_url_body
 FROM f''')
q('mixed_status_examples', '''WITH b AS (SELECT sha256 FROM c WHERE sha256 IS NOT NULL
 GROUP BY 1 HAVING bool_or(http_status between 200 and 299) AND bool_or(http_status>=400))
 SELECT c.sha256,list(distinct http_status) statuses,min(context_url) example_url,
 min(media_type) media,min(bytes) original_size FROM c JOIN b USING(sha256) GROUP BY 1 LIMIT 5''')
q('old_keys_shared_between_docs', '''WITH x AS (
 SELECT unnest(body_keys) body_key,document_id FROM d)
 SELECT count(*) bodies_in_multiple_documents, max(docs) most_docs FROM (
 SELECT body_key,count(distinct document_id) docs FROM x GROUP BY 1 HAVING docs>1)''')
q('shared_nonempty_good_format_keys', '''WITH x AS (
 SELECT unnest(body_keys) body_key,document_id FROM d), multi AS (
 SELECT body_key,count(distinct document_id) docs FROM x GROUP BY 1 HAVING docs>1),
 bodies AS (SELECT body_key,max(bytes) original_size,
 bool_or(http_status between 200 and 299) ok FROM c GROUP BY 1)
 SELECT count(*) bodies, max(m.docs) max_documents FROM multi m JOIN r USING(body_key)
 JOIN bodies USING(body_key) WHERE list_contains(r.body_format,'html') AND original_size>2048
 AND ok AND NOT list_contains(coalesce(r.record_role,[]),'error-response')''')
q('shared_key_example', '''WITH x AS (SELECT unnest(body_keys) body_key,document_id FROM d),
 multi AS (SELECT body_key,count(distinct document_id) docs FROM x GROUP BY 1 HAVING docs>1)
 SELECT f.filename,f.source_url,m.body_key,m.docs FROM multi m JOIN f USING(body_key)
 JOIN r USING(body_key) WHERE list_contains(r.body_format,'html') ORDER BY docs LIMIT 5''')
con.close()
