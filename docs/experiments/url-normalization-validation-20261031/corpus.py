from common import *
import sys
c=connect();only=set(sys.argv[1:]);result=json.loads((OUT/'corpus-results.json').read_text()) if only else {}
def q(name,sql):
 if only and name not in only:return
 result[name]={'sql':sql,'rows':rows(c,sql)}
 print(name,json.dumps(result[name]['rows'],default=str)[:1600],flush=True)
c.execute("CREATE OR REPLACE TABLE repairs AS SELECT s.*,d0.disposition AS before_disposition,d.disposition AS after_disposition,d.target_requirement FROM selected s LEFT JOIN d0 ON s.target_url=d0.target_url LEFT JOIN d ON s.target_url=d.target_url WHERE s.candidate_source='repaired_download_query'")
c.execute(f"CREATE OR REPLACE TABLE wave4 AS SELECT * FROM read_json_auto('{FROZEN/'wave4.json'}')")
c.execute(f"CREATE OR REPLACE TABLE wave5 AS SELECT * FROM read_json_auto('{OUT/'inputs/wave5results.json'}')")
q('repair_population',"SELECT before_disposition,after_disposition,target_requirement,count(*) AS targets,count(DISTINCT body_sha256) AS distinct_bodies FROM repairs GROUP BY ALL")
q('repair_body_novelty',"""WITH bodies AS (SELECT DISTINCT body_sha256 FROM repairs WHERE before_disposition='needs_acquisition' AND after_disposition='accepted_recovery')
SELECT count(*) AS bodies,count(*) FILTER(WHERE EXISTS(SELECT 1 FROM relevant_captures c WHERE c.body_sha=b.body_sha256 AND c.is_real_file)) AS prior_real_file_bodies,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM docs d WHERE lower(hex(d.saved_body))=b.body_sha256)) AS published_saved_bodies FROM bodies b""")
q('repair_duplicate_examples',"SELECT body_sha256,count(*) AS targets,list(target_url) AS urls FROM repairs WHERE before_disposition='needs_acquisition' AND after_disposition='accepted_recovery' GROUP BY ALL HAVING count(*)>1 ORDER BY targets DESC LIMIT 12")
q('repair_receipt_bindings',"""SELECT count(*) AS selected_targets,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM wave4 w WHERE w.final_url=r.candidate_url AND w.body_sha256=r.body_sha256 AND w.qualification_status='qualified')) AS wave4_body_bound,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM retained c WHERE c.original_url=r.target_url AND lower(hex(c.sha256))=r.body_sha256 AND c.complete AND c.mode='retained_import')) AS retained_bound,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM decisions d WHERE d.original_url=r.target_url AND d.body_sha256=r.body_sha256 AND d.acceptance_status='accepted')) AS decision_bound
FROM repairs r""")
q('amp_repair_novelty',"""SELECT count(*) AS targets,count(DISTINCT body_sha256) AS bodies,
count(DISTINCT body_sha256) FILTER(WHERE EXISTS(SELECT 1 FROM docs d WHERE lower(hex(d.saved_body))=r.body_sha256)) AS prior_published_bodies,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM wave4 w WHERE w.final_url=r.candidate_url AND w.body_sha256=r.body_sha256 AND w.qualification_status='qualified')) AS wave4_body_bound
FROM repairs r WHERE ends_with(target_url,'&download=1')""")
q('remaining_house_wave4',"""SELECT w.http_status,w.outcome,w.qualification_status,count(DISTINCT d.target_url) AS targets
FROM d LEFT JOIN wave4 w ON w.candidate_url=regexp_replace(d.target_url,'(?:%20|\\s)*&download=1$','?download=1')
WHERE d.disposition='needs_acquisition' AND ends_with(d.target_url,'&download=1') AND contains(d.target_url,'.house.gov/') GROUP BY ALL""")
q('remaining_house_wave5',"""SELECT w.http_status,w.outcome,w.qualification_status,count(DISTINCT d.target_url) AS targets
FROM d LEFT JOIN wave5 w ON w.candidate_url=regexp_replace(d.target_url,'(?:%20|\\s)*&download=1$','?download=1')
WHERE d.disposition='needs_acquisition' AND ends_with(d.target_url,'&download=1') AND contains(d.target_url,'.house.gov/') GROUP BY ALL""")
q('changed_key_capture_shapes',"""SELECT n.url,n.baseline_key,n.proposed_key,c.http_status,c.record_role,c.is_real_file,c.body_sha,c.bytes,count(*) AS rows
FROM normalized n LEFT JOIN relevant_captures c ON c.requested_url=n.url
WHERE n.baseline_key IS DISTINCT FROM n.proposed_key GROUP BY ALL ORDER BY n.url""")
q('finance_clean_target',"""SELECT requested_url,url,http_status,record_role,is_real_file,body_sha,bytes FROM relevant_captures
WHERE contains(requested_url,'the-presidents-fiscal-year-2024-irs-budget-and-the-irss-2023-filing-season')""")
q('aliases',"""SELECT s.*,d.disposition,st.capture_disposition,
EXISTS(SELECT 1 FROM relevant_captures c WHERE c.body_sha=s.body_sha256 AND c.is_real_file) AS prior_real_file,
EXISTS(SELECT 1 FROM docs x WHERE lower(hex(x.saved_body))=s.body_sha256) AS published_saved_body,
EXISTS(SELECT 1 FROM retained c WHERE c.original_url=s.target_url AND lower(hex(c.sha256))=s.body_sha256 AND c.complete) AS retained_bound,
EXISTS(SELECT 1 FROM decisions z JOIN requirements r ON z.original_url=r.original_url WHERE z.original_url=s.target_url AND z.body_sha256=s.body_sha256 AND z.acceptance_status='accepted' AND z.target_requirement=r.target_requirement AND z.acceptance_policy=r.acceptance_policy) AS decision_requirement_bound
FROM selected s LEFT JOIN d ON s.target_url=d.target_url LEFT JOIN st ON s.target_url=st.requested_url WHERE candidate_source='stored_url_key_alias'""")
# A redirect-only filter must be evaluated against all alternative entrances to the URL universe.
c.execute("CREATE OR REPLACE TABLE error_addresses AS SELECT DISTINCT url FROM captures WHERE mode='fetch' AND outcome NOT IN ('reference','saved-record') AND record_role='error_response' AND url IS NOT NULL")
q('error_address_removal',"""SELECT count(*) AS error_urls,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM captures c WHERE c.requested_url=e.url AND c.mode='fetch' AND c.outcome NOT IN ('reference','saved-record'))) AS also_requested,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM sources s WHERE s.url=e.url)) AS published_sources,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM links l WHERE l.target_url=e.url)) AS published_link_targets,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM d WHERE d.target_url=e.url AND d.disposition='accepted_recovery')) AS accepted_recovery_targets,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM captures c WHERE c.url=e.url AND c.is_real_file)) AS also_real_file
FROM error_addresses e""")
q('senate_error_candidates',"""SELECT e.url,d.disposition,st.capture_disposition,s.candidate_url,s.body_sha256
FROM error_addresses e LEFT JOIN d ON e.url=d.target_url LEFT JOIN st ON e.url=st.requested_url LEFT JOIN selected s ON e.url=s.target_url WHERE contains(e.url,'/404?notfound=')""")
q('malformed_families',"""SELECT CASE WHEN starts_with(url,'mailto:') THEN 'mailto' WHEN contains(url,'File URL path:') THEN 'File URL path' WHEN contains(url,'/cgi-lis/t2GPO/') THEN 'lis_gpo_wrapper' WHEN contains(url,'exit.asp?link=') THEN 'exit_wrapper' WHEN contains(url,'web.archive.org/web/') THEN 'wayback_wrapper' ELSE 'other_nested' END AS category,count(*) AS urls FROM all_urls WHERE starts_with(url,'mailto:') OR contains(url,'File URL path:') OR regexp_matches(url,'(?i)^https?://.+https?://') GROUP BY ALL""")
q('wrapper_doc_pairs',"""WITH pairs AS (SELECT DISTINCT d.target_url,regexp_replace(d.target_url,'&download=1$','') AS base_url FROM d WHERE ends_with(d.target_url,'&download=1'))
SELECT count(*) AS pairs,count(*) FILTER(WHERE EXISTS(SELECT 1 FROM captures c WHERE c.requested_url=p.base_url AND c.record_role='wrapper')) AS with_wrapper,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM captures c WHERE c.requested_url=p.base_url AND c.record_role='wrapper') AND EXISTS(SELECT 1 FROM selected s WHERE s.target_url=p.target_url)) AS wrapper_and_selected_file,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM sources s WHERE s.url=p.base_url)) AS base_published,
count(*) FILTER(WHERE EXISTS(SELECT 1 FROM sources s WHERE s.url=p.target_url)) AS amp_published
FROM pairs p""")
dump('corpus-results.json',result)
c.close()
