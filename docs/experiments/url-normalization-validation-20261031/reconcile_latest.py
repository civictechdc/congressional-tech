"""Freeze the later campaign generation and reconcile status counts, not semantics."""
from common import *
import subprocess
work=OUT/'reconciliation';work.mkdir(exist_ok=True)
inputs={};paths={
 'latest_plan':CAM/'plan_v2/url-dispositions.parquet',
 'latest_selected':CAM/'track_a/selected_recoveries_v2_plus.parquet',
 'latest_state':CAM/'release_v2/url_state.parquet',
 'wave6_qualified':CAM/'track_b/b1_wave6_qualified.json',
 'wave6_results':CAM/'track_b/b1_wave6_results.json',
 'trace_before':REPO/'docs/url-normalization-trace.md',
 'defense_before':REPO/'docs/url-normalization-defense.md',
 'response_before':REPO/'docs/url-normalization-defense-response.md'}
for name,source in paths.items():
 dest=work/(name+source.suffix)
 if not dest.exists():
  before=source.stat();shutil.copy2(source,dest);after=source.stat()
  assert (before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns)
 inputs[name]={'source':str(source),'path':str(dest),'sha256':hashlib.file_digest(dest.open('rb'),'sha256').hexdigest(),'bytes':dest.stat().st_size}
c=duckdb.connect(config={'threads':2,'memory_limit':'1GB'})
for name,p in [('baseline',FROZEN/'plan.parquet'),('gen2',FROZEN/'plan_v2.parquet'),('selected2',FROZEN/'selected.parquet')]+[(k,Path(v['path'])) for k,v in inputs.items() if v['path'].endswith('.parquet')]:
 c.execute(f"CREATE VIEW {name} AS SELECT * FROM '{p}'")
r={'scope':'Status and lineage reconciliation only; no new independent semantic qualification of Wave 6 bodies.',
 'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'inputs':inputs}
r['dispositions']={n:rows(c,f'SELECT disposition,count(*) AS targets FROM {n} GROUP BY ALL ORDER BY ALL') for n in ['baseline','gen2','latest_plan']}
r['baseline_pending_transitions']=rows(c,"SELECT l.disposition,count(*) AS targets FROM baseline b JOIN latest_plan l USING(target_url) WHERE b.disposition='needs_acquisition' GROUP BY ALL ORDER BY ALL")
r['gen2_pending_transitions']=rows(c,"SELECT l.disposition,count(*) AS targets FROM gen2 b JOIN latest_plan l USING(target_url) WHERE b.disposition='needs_acquisition' GROUP BY ALL ORDER BY ALL")
r['latest_selected_sources']=rows(c,'SELECT candidate_source,count(*) AS targets,count(DISTINCT body_sha256) AS bodies FROM latest_selected GROUP BY ALL ORDER BY targets DESC')
r['selected_additions']=rows(c,"SELECT l.candidate_source,count(*) AS targets,count(DISTINCT l.body_sha256) AS bodies FROM latest_selected l ANTI JOIN selected2 b USING(target_url) GROUP BY ALL ORDER BY targets DESC")
r['selected_totals']=rows(c,'SELECT count(*) AS targets,count(DISTINCT target_url) AS unique_targets,count(DISTINCT body_sha256) AS bodies FROM latest_selected')
r['selected2_totals']=rows(c,'SELECT count(*) AS targets,count(DISTINCT target_url) AS unique_targets,count(DISTINCT body_sha256) AS bodies FROM selected2')
r['selected_but_excluded']=rows(c,"SELECT s.target_url,s.candidate_source,p.disposition,p.subtype FROM latest_selected s LEFT JOIN latest_plan p USING(target_url) WHERE p.disposition IS DISTINCT FROM 'accepted_recovery'")
r['all_baseline_transitions']=rows(c,"SELECT b.disposition AS before,l.disposition AS after,count(*) AS targets FROM baseline b JOIN latest_plan l USING(target_url) GROUP BY ALL ORDER BY ALL")
r['amp_generations']={n:rows(c,f"SELECT disposition,count(*) AS targets FROM {n} WHERE ends_with(target_url,'&download=1') GROUP BY ALL ORDER BY ALL") for n in ['baseline','gen2','latest_plan']}
r['retained_amp_subtypes']=rows(c,"SELECT disposition,subtype,count(*) AS targets FROM gen2 WHERE ends_with(target_url,'&download=1') AND disposition='accepted_recovery' GROUP BY ALL ORDER BY targets DESC")
r['bill_4824_current']=rows(c,"SELECT l.target_url,l.disposition,l.subtype,s.body_sha256,s.candidate_source FROM latest_plan l LEFT JOIN latest_selected s USING(target_url) WHERE contains(l.target_url,'/hr-4824')")
r['ashley_current']=rows(c,"SELECT * FROM latest_state WHERE contains(requested_url,'ashley-nunes-witness-testimony')")
r['wave6_qualified_sources']=rows(c,f"SELECT source_kind,count(*) AS rows FROM read_json_auto('{inputs['wave6_qualified']['path']}') GROUP BY ALL ORDER BY rows DESC")
r['wave6_result_sources']=rows(c,f"SELECT source_kind,count(*) AS rows,count(*) FILTER(WHERE qualification_status='qualified') AS qualified FROM read_json_auto('{inputs['wave6_results']['path']}') GROUP BY ALL ORDER BY rows DESC")
dump('reconciliation-results.json',r)
(HERE/'evidence/reconciliation-results.json').write_text(json.dumps(r,indent=2,default=str)+'\n')
print(json.dumps({k:v for k,v in r.items() if k not in ('inputs','latest_selected_sources','retained_amp_subtypes')},indent=2,default=str))
