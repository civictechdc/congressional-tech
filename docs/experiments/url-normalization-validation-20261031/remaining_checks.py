"""Real malformed literals and accepted aliases, through the native URL functions."""
from common import *
import os,re
from congress_api.retention.provenance import json_input,run_job,parquet_output
from docspec_client.client import NativeDatasets

os.environ['DOCSPEC_JOB_CONFIG']=str(OLD/'runtime.json')
c=connect(); work=OUT/'remaining';work.mkdir(exist_ok=True)
aliases=rows(c,"SELECT * FROM selected WHERE candidate_source='stored_url_key_alias'")
malformed=rows(c,"SELECT * FROM malformed_raw WHERE starts_with(href,'mailto:http') OR contains(href,'File URL path:') OR contains(href,'congress.gov/cgi-lis')")
for x in malformed:
 contexts=rows(c,'SELECT DISTINCT context_url FROM captures WHERE body_sha=? AND context_url IS NOT NULL',[x['page_body']])
 x['context']=contexts[0]['context_url'] if contexts else None
 if x['href'].startswith('mailto:'):x['candidate']=x['href'][7:]
 elif 'File URL path:' in x['href']:x['candidate']=x['href'].split('File URL path:',1)[1].strip()
 else:x['candidate']=x['href'].split('/cgi-lis/t2GPO/',1)[1]
values=sorted({v for x in aliases for v in (x['target_url'],x['candidate_url'])})
inputs=[json_input(work,'url_inputs',[{'input_id':str(i),'url':v} for i,v in enumerate(values)],input_id='Utf8',url='Utf8'),
 json_input(work,'url_rules',json.loads((REPO/'model/registries/url-rules.json').read_text()),id='Utf8',kind='Utf8',host_pattern='Utf8',pattern='Utf8',replacement='Utf8',decoder='Utf8'),
 {'name':'url_variants','kind':'parquet','path':str(OUT/'inputs/variants.parquet')},
 json_input(work,'malformed',malformed,audit_row='UInt64',page_body='Utf8',title='Utf8',base_href='Utf8',href='Utf8',text='Utf8',context='Utf8',candidate='Utf8')]
c.close()
run_job(work,NativeDatasets.from_config(os.environ['DOCSPEC_JOB_CONFIG']),inputs=inputs,
 steps=[{'name':'alias_keys','sql':(REPO/'model/sql/url-normalized.sql').read_text(),'materialize':True}],
 outputs=[parquet_output(work,'alias_keys','SELECT * FROM alias_keys',['url']),
 parquet_output(work,'malformed_resolved',"SELECT *,url_resolve(href,context) AS baseline_resolved,url_resolve(candidate,context) AS proposed_resolved FROM malformed",['audit_row'])],queries=[])
c=connect();c.execute(f"CREATE OR REPLACE VIEW alias_keys AS SELECT * FROM '{work/'alias_keys.parquet'}'")
c.execute(f"CREATE OR REPLACE VIEW malformed_resolved AS SELECT * FROM '{work/'malformed_resolved.parquet'}'")
r={}
r['alias_keys']=rows(c,"""SELECT s.target_url,s.candidate_url,s.body_sha256,a.base_key AS target_key,b.base_key AS candidate_key,a.error AS target_error,b.error AS candidate_error
FROM selected s JOIN alias_keys a ON s.target_url=a.url JOIN alias_keys b ON s.candidate_url=b.url WHERE candidate_source='stored_url_key_alias'""")
r['malformed']=rows(c,"SELECT * FROM malformed_resolved")
for x in r['malformed']:
 x['baseline_admitted']=bool(x['baseline_resolved'] and re.match('^https?://',x['baseline_resolved']))
 x['proposed_admitted']=bool(x['proposed_resolved'] and re.match('^https?://',x['proposed_resolved']))
 x['retained_exact']=rows(c,"SELECT DISTINCT requested_url,url,body_sha,format,is_real_file,record_role,outcome FROM captures WHERE requested_url=? OR url=?",[x['proposed_resolved']]*2)
 bill=re.search('BILLS-[^/]+[.]pdf',x['candidate'])
 if bill:
  x['bill_published']=rows(c,"SELECT DISTINCT s.url,d.document_id,d.title,d.format,lower(hex(d.saved_body)) AS body FROM sources s JOIN docs d USING(list_row) WHERE contains(s.url,?)",[bill[0]])
 else:x['bill_published']=[]
r['alias_publication']=rows(c,f"""SELECT s.target_url,s.candidate_url,s.body_sha256,
 (SELECT count(*) FROM sources p WHERE p.url=s.target_url) AS exact_target_source_rows,
 (SELECT count(*) FROM sources p WHERE p.url=s.candidate_url) AS exact_candidate_source_rows,
 (SELECT count(*) FROM docs d WHERE lower(hex(d.saved_body))=s.body_sha256) AS saved_document_rows,
 (SELECT count(*) FROM read_parquet('{PUB/'release/recoveries.parquet'}') r WHERE lower(hex(r.body))=s.body_sha256) AS published_recovery_rows
FROM selected s WHERE candidate_source='stored_url_key_alias'""")
exceptions=[x['body_sha256'] for x in aliases if x['body_sha256'] in ('1b5facc7dfe4707f44f21a6b75f0e29d9ab3579e325398edfdca70511240d345','24e5987d0cd3cf5ec5e41d085779ac0fa95fb9c6c25d02c29dee04fe797f3437')]
r['exception_readings']=rows(c,'SELECT * FROM facts WHERE lower(hex(body_sha)) IN (SELECT unnest(?))',[exceptions])
dump('remaining-results.json',r)
print(json.dumps({'alias_key_equal':sum(x['target_key']==x['candidate_key'] and not(x['target_error'] or x['candidate_error']) for x in r['alias_keys']),
 'malformed':[{'href':x['href'],'baseline_admitted':x['baseline_admitted'],'proposed_admitted':x['proposed_admitted'],'retained_exact':len(x['retained_exact']),'published_bill_rows':len(x['bill_published'])} for x in r['malformed']]},indent=2))
