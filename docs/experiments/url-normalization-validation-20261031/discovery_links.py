from common import *
import os
from congress_api.retention.provenance import json_input,run_job,parquet_output
from docspec_client.client import NativeDatasets
os.environ['DOCSPEC_JOB_CONFIG']=str(OLD/'runtime.json')
c=connect()
c.execute("""CREATE OR REPLACE TABLE audit_page_contexts AS SELECT body_sha AS page_body,context_url,member_path,min(retrieved_at) AS first_good_at,max(retrieved_at) AS last_good_at
FROM captures WHERE body_sha IS NOT NULL AND context_url IS NOT NULL AND complete AND outcome IN ('stored','unchanged') AND record_role='wrapper' GROUP BY ALL""")
c.execute(f"COPY audit_page_contexts TO '{OUT/'page-contexts.parquet'}' (FORMAT PARQUET)")
context_count=c.execute('SELECT count(*) FROM audit_page_contexts').fetchone()[0];c.close()
job=json.loads((PUB/'model/job.json').read_text());work=OUT/'discovery-links';work.mkdir(exist_ok=True)
inputs=[i for i in job['inputs'] if i['name'] in ('readings','parser_versions','file_shapes')]
for item in inputs:
 if item['name']=='readings':item['name']='raw_readings'
inputs.append({'name':'page_contexts','kind':'parquet','path':str(OUT/'page-contexts.parquet')})
rules=json.loads((REPO/'model/registries/url-rules.json').read_text())
inputs.append(json_input(work,'url_rules',rules,id='Utf8',kind='Utf8',host_pattern='Utf8',pattern='Utf8',replacement='Utf8',decoder='Utf8'))
names=['link_inputs','link_contexts','link_literals','link_parts','link_targets','link_errors','resolved_links']
steps=[dict(name='readings',sql="SELECT r.body_sha,r.parser,r.parser_version,r.links,r.base_href FROM raw_readings r WHERE r.parser IN ('html','xml','json') AND encode(r.body_sha,'hex') IN (SELECT page_body FROM page_contexts)",materialize=True)]
for name in names:
 original=next(s for s in job['steps'] if s['name']==name)
 s={'name':name,'sql':original['sql'],'materialize':True}
 path=REPO/'model/sql'/name.replace('_','-');path=path.with_suffix('.sql')
 if path.exists():s['sql']=path.read_text()
 s['materialize']=True;steps.append(s)
steps.append(dict(name='audit_counts',sql="SELECT 'extracted' AS stage,count(*) AS rows FROM link_inputs UNION ALL SELECT 'resolved',count(*) FROM resolved_links UNION ALL SELECT 'errors',count(*) FROM link_errors",materialize=True))
outputs=[parquet_output(work,'audit_links',"SELECT row_number() OVER(ORDER BY page_body,context_url,link_index,href) AS audit_row,page_body,context_url,link_index,href,text,target_url FROM resolved_links WHERE strpos(target_url,'/download/')>0 OR context_url='https://democrats-science.house.gov/download/ashley-nunes-witness-testimony'",['audit_row'])]
result=run_job(work,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,steps=steps,outputs=outputs,queries=[dict(name='counts',sql='SELECT * FROM audit_counts')])
c=connect();c.execute(f"CREATE OR REPLACE VIEW wrapper_links AS SELECT * FROM read_parquet('{work/'audit_links.parquet'}')")
summary={'contexts':context_count,'native_counts':result,
 'amp_discovery':rows(c,"""SELECT count(DISTINCT l.target_url) AS amp_targets,count(DISTINCT l.target_url) FILTER(WHERE EXISTS(SELECT 1 FROM st WHERE requested_url=l.target_url)) AS in_state,
count(DISTINCT l.target_url) FILTER(WHERE EXISTS(SELECT 1 FROM links p WHERE p.target_url=l.target_url)) AS in_publisher_links,
count(DISTINCT l.target_url) FILTER(WHERE EXISTS(SELECT 1 FROM selected s WHERE s.target_url=l.target_url)) AS selected_recovery
FROM wrapper_links l WHERE ends_with(l.target_url,'&download=1')"""),
 'ashley':rows(c,"""SELECT href,text,target_url,EXISTS(SELECT 1 FROM st WHERE requested_url=l.target_url) AS exact_state FROM wrapper_links l WHERE context_url='https://democrats-science.house.gov/download/ashley-nunes-witness-testimony'"""),
 'bill_4824':rows(c,"SELECT href,text,target_url FROM wrapper_links WHERE context_url='https://democrats-science.house.gov/download/hr-4824' AND (contains(href,'4824') OR contains(text,'4824'))")}
dump('discovery-link-results.json',summary);print(json.dumps({k:v for k,v in summary.items() if k!='ashley'},indent=2))
