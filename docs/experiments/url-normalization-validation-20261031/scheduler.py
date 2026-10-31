from common import *
import os,sys,inspect
import pyarrow as pa
import pyarrow.parquet as pq
from congress_api.acquisition import capture_scheduler as scheduler
from congress_shared.campaign import load_campaign
os.environ['DOCSPEC_JOB_CONFIG']=str(OLD/'runtime.json')
sys.path.insert(0,str(REPO/'packages/congress_api/tests'))
from test_capture_scheduler import release,load,engine,write_manifest
c=connect();scope=PUB/'release/capture_scope.json';policy=scheduler.CapturePolicy(scope)
sqlscope=policy.sql('url').replace('regexp_like','regexp_matches')
c.execute(f"CREATE OR REPLACE TABLE scoped_campaign AS SELECT *,{sqlscope} AS scope_family FROM (SELECT *,target_url AS url FROM campaign_keys)")
groups=rows(c,"""WITH g AS (SELECT current_key,min(url) AS selected,min(url) FILTER(WHERE scope_family IS NOT NULL) AS admissible,count(*) AS literals FROM scoped_campaign WHERE current_key IS NOT NULL GROUP BY current_key)
SELECT count(*) FILTER(WHERE starts_with(selected,'http://') AND admissible IS NOT NULL) AS groups_http_before_scope,
count(*) FILTER(WHERE ends_with(selected,'&download=1') AND literals>1) AS groups_amp_preferred,
count(*) FILTER(WHERE selected IS DISTINCT FROM admissible AND admissible IS NOT NULL) AS groups_with_better_scope_choice FROM g""")
http=rows(c,"""SELECT current_key,list(url ORDER BY url) AS urls FROM scoped_campaign WHERE starts_with(url,'http://') OR starts_with(url,'https://') GROUP BY current_key HAVING bool_or(starts_with(url,'http://')) AND bool_or(scope_family IS NOT NULL) ORDER BY current_key LIMIT 3""")
amp='https://democrats-science.house.gov/download/ashley-nunes-witness-testimony&download=1';good=amp.replace('&download=1','?download=1')
state=rows(c,'SELECT * FROM st WHERE requested_url=?',[amp])[0]
http_group=next(r for r in http if any(u.startswith('https://') for u in r['urls']))
http_urls=[next(u for u in http_group['urls'] if u.startswith('http://')),next(u for u in http_group['urls'] if u.startswith('https://'))]
http_states=rows(c,'SELECT * FROM st WHERE requested_url IN (SELECT unnest(?))',[http_urls])
entries=json.loads(scope.read_text())['entries'];c.close()
results={}
def scenario(name,states,seeds,*,campaign=False,replace_candidate=False):
 work=OUT/'scheduler'/name;work.mkdir(parents=True,exist_ok=True)
 root=release(work,states,entries=entries)
 seed=work/'seeds.json';seed.write_text(json.dumps({'urls':seeds}))
 descriptor=None
 if campaign:
  table=pq.read_table(root/'url_state.parquet')
  for key in ['capture_disposition','capture_reason','capture_decision_id']:table=table.append_column(key,pa.array([r.get(key) for r in states],type=pa.string()))
  pq.write_table(table,root/'url_state.parquet')
  requirements=work/'requirements.parquet';target=work/'targets.parquet';candidate=work/'candidates.parquet'
  pq.write_table(pa.table({'original_url':[amp],'target_requirement':['historical_exact'],'acceptance_policy':['recovery-identity-v1']}),requirements)
  pq.write_table(pa.table({'target_url':[amp]}),target)
  pq.write_table(pa.table({'target_url':[amp],'candidate_url':[good]}),candidate)
  profile=json.loads((root/'capture_profile.json').read_text());profile.update(version=2,recovery_policy={'acceptance_policy':'recovery-identity-v1','requirements_sha256':hashlib.sha256(requirements.read_bytes()).hexdigest()})
  (root/'capture_profile.json').write_text(json.dumps(profile));write_manifest(root)
  def binding(path):return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
  descriptor=work/'campaign.json';descriptor.write_text(json.dumps({'version':1,'campaign_id':'real-target-audit','requirement':'historical_exact','tables':{'targets':binding(target),'candidates':binding(candidate),'requirements':binding(requirements)},'target_table':'targets','candidate_table':'candidates'}))
 planner=scheduler.plan_queue
 if replace_candidate:
  # Deliberately test the proposed minimal address substitution independently of
  # a proper two-field campaign implementation. Inputs are real retained rows.
  src=inspect.getsource(planner).replace('SELECT requested_url,attempts,cast(last_outcome',f"SELECT CASE WHEN requested_url='{amp}' THEN '{good}' ELSE requested_url END AS requested_url,attempts,cast(last_outcome")
  namespace=dict(vars(scheduler));exec(src,namespace);planner=namespace['plan_queue']
 with engine() as native:
  result=planner(load(root,work/'read'),engine=native,work=work/'plan',as_of='2026-10-31T23:59:59Z',request_budget=20,seed_inventories=[seed],campaign=load_campaign(descriptor) if descriptor else None)
 return {'input_states':states,'input_seeds':seeds,'queue':pq.read_table(result['queue']).to_pylist(),'candidate_substitution':replace_candidate,'campaign':campaign}
for name,states,seeds,options in [('mixed_amp_seeds',[],[amp,good],{}),('lone_amp_seed',[],[amp],{}),('existing_bad_state',[state],[good],{}),('mixed_http_seeds',[],http_urls,{}),('existing_http_states',http_states,[],{}),('campaign_actual',[state],[good],{'campaign':True}),('campaign_naive_substitution',[state],[good],{'campaign':True,'replace_candidate':True})]:
 results[name]=scenario(name,states,seeds,**options);print(name,[r['requested_url'] for r in results[name]['queue']],flush=True)
dump('scheduler-results.json',{'census':groups,'http_examples':http,'scenarios':results,'note':'Census uses retained campaign address groups, not the unavailable historical seed batches. Empty-state scenarios are explicitly counterfactual runs using real addresses; existing-state scenarios preserve retained state rows.'})
