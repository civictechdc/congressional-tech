from common import *
import os,copy
from congress_api.retention.provenance import json_input,run_job,parquet_output
from docspec_client.client import NativeDatasets

os.environ['DOCSPEC_JOB_CONFIG']=str(OLD/'runtime.json')
work=OUT/'normalize';work.mkdir(exist_ok=True)
rules=json.loads((REPO/'model/registries/url-rules.json').read_text())
proposed=copy.deepcopy(rules)
for r in proposed:
 if r['id']=='senate-notfound':
  r.update(pattern=r'(?i)^(https?://(?:[a-z0-9-]+\.)+senate\.gov)/404\?notfound=(?:%2f|/)?([^#]+)(?:#.*)?$',decoder='percent')
 if r['id']=='download-ampersand-query':r['pattern']=r['pattern'][:-1]+r'(?:#.*)?$'
inputs=[dict(name='url_inputs',kind='parquet',path=str(OUT/'risk-urls.parquet')),
 dict(name='url_variants',kind='parquet',path=str(OUT/'inputs/variants.parquet'))]
for name,value in [('url_rules',rules),('proposed_rules',proposed)]:
 inputs.append(json_input(work,name,value,id='Utf8',kind='Utf8',host_pattern='Utf8',pattern='Utf8',replacement='Utf8',decoder='Utf8'))
sql=(REPO/'model/sql/url-normalized.sql').read_text().replace('SELECT * FROM base_keys','SELECT b.*,u.value AS unwrapped FROM base_keys b JOIN unwrapped u ON b.url=u.url')
changed=sql.replace('url_rules','proposed_rules').replace("regexp_replace(c.path,'/$','')","regexp_replace(c.path,'(?:%20|/)+$','')")
steps=[dict(name='baseline',sql=sql,materialize=True),dict(name='proposed',sql=changed,materialize=True)]
output=parquet_output(work,'comparison',"""SELECT b.url,b.base_key AS baseline_key,p.base_key AS proposed_key,
 b.error AS baseline_error,p.error AS proposed_error,b.unwrapped AS baseline_fetch,p.unwrapped AS proposed_fetch
 FROM baseline b JOIN proposed p ON b.url=p.url ORDER BY b.url""",['url'])
result=json.loads((OUT/'normalize.json').read_text()) if (OUT/'normalize.json').exists() else run_job(work,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,steps=steps,outputs=[output],queries=[dict(name='counts',sql='SELECT count(*) AS inputs,count(*) FILTER(WHERE b.base_key IS DISTINCT FROM p.base_key) AS changed FROM baseline b JOIN proposed p ON b.url=p.url')])
dump('normalize.json',result)
c=connect();c.execute(f"CREATE OR REPLACE VIEW normalized AS SELECT * FROM read_parquet('{work/'comparison.parquet'}')")
c.execute('CREATE OR REPLACE TABLE campaign_keys AS SELECT k.*,coalesce(n.baseline_key,k.url_key) current_key,coalesce(n.proposed_key,k.url_key) proposed_key FROM k LEFT JOIN normalized n ON k.target_url=n.url')
summary={
 'counts':result,
 'changed_by_family':rows(c,"""SELECT CASE WHEN contains(url,'/404?notfound=') THEN 'senate_notfound' WHEN contains(url,'&download=1') THEN 'download_ampersand' ELSE 'trailing_trim' END AS family,count(*) AS urls FROM normalized WHERE baseline_key IS DISTINCT FROM proposed_key GROUP BY ALL"""),
 'published_changes':rows(c,'SELECT n.*,s.list_row FROM normalized n JOIN sources s ON n.url=s.url WHERE baseline_key IS DISTINCT FROM proposed_key'),
 'changed':rows(c,'SELECT * FROM normalized WHERE baseline_key IS DISTINCT FROM proposed_key'),
 'merges':rows(c,"""SELECT proposed_key,count(DISTINCT current_key) baseline_keys,list(DISTINCT target_url) urls FROM campaign_keys GROUP BY proposed_key HAVING count(DISTINCT current_key)>1 AND bool_or(current_key IS DISTINCT FROM proposed_key)""")}
dump('normalization-results.json',summary)
print(json.dumps({k:v for k,v in summary.items() if k not in ('changed','merges','published_changes')},indent=2))
print('published source changes',len(summary['published_changes']),'merged campaign groups',len(summary['merges']))
