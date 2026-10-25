from pathlib import Path
import json
import time
import duckdb

con=duckdb.connect('review.duckdb')
con.execute("SET threads = 4")
con.execute("SET memory_limit = '3GB'")
con.execute("SET temp_directory = './duckdb_tmp'")
results={}
def q(label,sql):
    t=time.perf_counter()
    cur=con.execute(sql)
    columns=[v[0] for v in cur.description]
    rows=[dict(zip(columns,r)) for r in cur.fetchall()]
    results[label]={'seconds':round(time.perf_counter()-t,3),'rows':rows}
    Path('design_case_measurements.json').write_text(json.dumps(results,indent=2,default=str))
    print(label,json.dumps(results[label],default=str),flush=True)

q('null_and_scalar_metadata', '''SELECT count(*) n,
  count(*) FILTER(WHERE source_url IS NULL) null_source_url,
  count(*) FILTER(WHERE len(document_kind)>1) multi_kind,
  count(*) FILTER(WHERE len(document_family)>1) multi_family,
  count(*) FILTER(WHERE len(committee_code)>1) multi_committee,
  count(*) FILTER(WHERE len(congress)>1) multi_congress,
  count(*) FILTER(WHERE len(measure_type)>1) multi_measure_type,
  count(*) FILTER(WHERE len(measure_number)>1) multi_measure_number FROM f''')
q('multivalue_cases', '''SELECT filename,source_url,document_kind,document_family,committee_code,congress,
  measure_type,measure_number FROM f WHERE len(document_kind)>1 OR len(congress)>1 OR len(committee_code)>1 LIMIT 8''')
q('archive_samples', '''SELECT context_url,original_path,pointer_json,sha256,reference_kind,media_type
  FROM c WHERE contains(pointer_json,'archive_members') LIMIT 6''')
q('archive_counts', '''SELECT count(*) n,count(distinct(context_url,original_path)) endpoints,
  count(*) FILTER(WHERE original_path IS NULL) missing_paths FROM c WHERE contains(pointer_json,'archive_members')''')
q('archive_identity_conflicts', '''WITH x AS (
  SELECT sha256,context_url,regexp_extract(original_path,'[^/]+$') basename,
    count(distinct original_path) paths, min(original_path) first_path,max(original_path) last_path
  FROM c WHERE contains(pointer_json,'archive_members') AND sha256 IS NOT NULL
  GROUP BY 1,2,3 HAVING count(distinct original_path)>1)
  SELECT count(*) ambiguous_keys,sum(paths) member_paths FROM x''')
q('archive_identity_conflict_examples', '''SELECT sha256,context_url,regexp_extract(original_path,'[^/]+$') basename,
    count(distinct original_path) paths, min(original_path) first_path,max(original_path) last_path
  FROM c WHERE contains(pointer_json,'archive_members') AND sha256 IS NOT NULL
  GROUP BY 1,2,3 HAVING count(distinct original_path)>1 ORDER BY paths DESC LIMIT 5''')
q('threshold_counts', '''WITH x AS (SELECT sha256,count(distinct context_url) urls FROM c
    WHERE sha256 IS NOT NULL GROUP BY 1)
  SELECT count(*) FILTER(WHERE urls>50) above_50,count(*) FILTER(WHERE urls>100) above_100,
  count(*) FILTER(WHERE urls>200) above_200 FROM x''')
q('pdf_body_size', '''WITH b AS (SELECT sha256,max(stored_bytes) nstored,max(bytes) original,
   bool_or(lower(media_type) LIKE 'application/pdf%') is_pdf FROM c WHERE sha256 IS NOT NULL GROUP BY 1)
  SELECT count(*) n,sum(nstored) stored_bytes,sum(original) original_bytes FROM b WHERE is_pdf''')
q('truncations', '''SELECT count(*) n,count(distinct sha256) bodies,count(distinct context_url) urls,
  min(bytes) smallest,max(bytes) largest FROM c WHERE bytes=67108864''')
q('bill_versions', '''SELECT filename,source_url,body_key,document_id,response_format,
  response_body_complete,response_result FROM f WHERE filename ILIKE '%112hr1063ih%' LIMIT 12''')
q('xml_roots', '''SELECT content_xml_root,count(*) n FROM f
    WHERE len(content_xml_root)>0 GROUP BY 1 ORDER BY n DESC LIMIT 12''')
q('capture_success_body_sharing', '''WITH b AS (SELECT sha256,
    bool_or(http_status between 200 and 299) good,
    bool_or(http_status>=400) bad FROM c WHERE sha256 IS NOT NULL GROUP BY 1)
    SELECT count(*) good_and_bad_bodies FROM b WHERE good AND bad''')

# Arithmetic checks use the rates implied by thesis costs, not a current cloud price quote.
results['cost_and_schedule_arithmetic']={
  'rate_provenance':'Rates inferred from thesis: storage $0.015/GB-month; GET $0.36/million; PUT $4.50/million.',
  'raw_storage_annual_estimate':696357882380/1e9*.015*12,
  'pdf_copy_annual_estimate':403210461951/1e9*.015*12,
  'sniff_GET_estimate':1036256/1e6*.36,
  'pdf_PUT_estimate':261055/1e6*4.5,
  'full_duplicate_originals_storage_annual_estimate':763170433578/1e9*.015*12,
  'all_tracks_person_weeks':{'min':2+1+3.75+1.5+3.5+1,'max':3.5+2+6+3+6.5+2},
  'listed_C_subtasks_person_weeks':{'min':.5+.5+1.25+.5+.5+.5,'max':1.5+.5+2+.5+.5+1},
  'sniff_requests_per_second_to_finish_one_hour':1036256/3600,
  'sample_25_random_detection_if_one_bad_body':25/1036256,
  'sample_25_random_detection_if_1percent_bad':1-.99**25,
}
Path('design_case_measurements.json').write_text(json.dumps(results,indent=2,default=str))
print('cost_and_schedule_arithmetic',json.dumps(results['cost_and_schedule_arithmetic']))
con.close()
