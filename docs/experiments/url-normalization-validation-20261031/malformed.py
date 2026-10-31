from common import *
import gzip,os
from congress_api.retention.provenance import run_job,parquet_output,json_input
from docspec_client.client import NativeDatasets
os.environ['DOCSPEC_JOB_CONFIG']=str(OLD/'runtime.json')
job=json.loads((PUB/'model/job.json').read_text());work=OUT/'malformed';work.mkdir(exist_ok=True)
input=next(i for i in job['inputs'] if i['name']=='readings')
with gzip.open(PUB/'model/parser_versions.jsonl.gz','rt') as f:versions=[json.loads(l) for l in f]
pred=' OR '.join("(parser='%s' AND parser_version='%s')"%(v['parser'],v['version']) for v in versions if v['parser'] in ('html','xml','json'))
sql=f"""WITH expanded AS (SELECT encode(body_sha,'hex') AS page_body,title,base_href,unnest(links) AS link FROM readings WHERE {pred})
SELECT DISTINCT page_body,title,base_href,link['href'] AS href,link['text'] AS text FROM expanded
WHERE regexp_like(link['href'],'(?i)^mailto:https?://|File URL path:|^https?://.+https?://')"""
export="SELECT row_number() OVER(ORDER BY page_body,href,text) AS audit_row,* FROM ("+sql+")"
result=run_job(work,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=[input],steps=[],outputs=[parquet_output(work,'raw_candidates',export,['audit_row'])],queries=[])
c=connect();c.execute(f"CREATE OR REPLACE VIEW malformed_raw AS SELECT * FROM read_parquet('{work/'raw_candidates.parquet'}')")
summary={
 'counts':rows(c,"""SELECT CASE WHEN starts_with(href,'mailto:') THEN 'mailto_http' WHEN contains(href,'File URL path:') THEN 'file_url_prefix' WHEN contains(href,'web.archive.org/') THEN 'wayback_wrapper' WHEN contains(href,'/cgi-lis/t2GPO/') THEN 'gpo_wrapper' WHEN contains(href,'exit.asp?link=') THEN 'exit_wrapper' ELSE 'other_nested' END AS category,count(*) AS link_rows,count(DISTINCT href) AS literals FROM malformed_raw GROUP BY ALL"""),
 'prefixes':rows(c,"SELECT DISTINCT r.*,c.context_url FROM malformed_raw r LEFT JOIN captures c ON r.page_body=c.body_sha WHERE starts_with(href,'mailto:') OR contains(href,'File URL path:')"),
 'unrecognized_wrappers':rows(c,"SELECT DISTINCT href,text FROM malformed_raw WHERE contains(href,'congress.gov/cgi-lis') OR contains(href,'exit.asp?link=')")}
dump('malformed-results.json',summary);print(json.dumps(summary,indent=2)[:12000])
