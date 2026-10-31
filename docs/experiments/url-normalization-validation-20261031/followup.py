from common import *
c=connect();r={}
c.execute("""CREATE OR REPLACE TABLE error_other_routes AS SELECT e.url,bool_or(route='context') AS context_route,bool_or(route='source') AS source_route,bool_or(route='other_capture') AS other_capture_route
FROM error_addresses e JOIN (
 SELECT context_url AS url,'context' AS route FROM captures WHERE context_url IS NOT NULL AND outcome NOT IN ('reference','saved-record')
 UNION ALL SELECT source_url AS url,'source' AS route FROM captures WHERE source_url IS NOT NULL AND body_sha IS NOT NULL AND member_path IS NULL
 UNION ALL SELECT unnest([requested_url,url]) AS url,'other_capture' AS route FROM captures WHERE mode='fetch' AND outcome NOT IN ('reference','saved-record') AND record_role IS DISTINCT FROM 'error_response'
) x ON e.url=x.url GROUP BY e.url""")
r['error_filter']=rows(c,"""SELECT count(*) AS error_urls,count(*) FILTER(WHERE r.context_route) AS context_route,count(*) FILTER(WHERE r.source_route) AS source_address_route,count(*) FILTER(WHERE r.url IS NULL) AS possibly_removed FROM error_addresses e LEFT JOIN error_other_routes r ON e.url=r.url""")
r['senate_filter']=rows(c,"""SELECT count(*) AS senate_error_urls,count(*) FILTER(WHERE r.url IS NOT NULL) AS survive_other_model_input_routes FROM error_addresses e LEFT JOIN error_other_routes r ON e.url=r.url WHERE contains(e.url,'/404?notfound=')""")
r['nested_hosts']=rows(c,"SELECT regexp_extract(href,'^https?://([^/]+)',1) AS host,count(DISTINCT href) AS literals FROM malformed_raw WHERE regexp_matches(href,'(?i)^https?://.+https?://') GROUP BY host ORDER BY literals DESC LIMIT 12")
r['aliases']=json.loads((OUT/'corpus-results.json').read_text())['aliases']['rows']
r['alias_counts']={k:sum(x[k] is True for x in r['aliases']) for k in ['prior_real_file','published_saved_body','retained_bound','decision_requirement_bound']}
r['alias_key_pairs']=rows(c,"""SELECT s.target_url,s.candidate_url,s.body_sha256,coalesce(a.baseline_key,k.current_key) AS target_key,b.baseline_key AS candidate_key FROM selected s LEFT JOIN normalized a ON s.target_url=a.url LEFT JOIN campaign_keys k ON s.target_url=k.target_url LEFT JOIN normalized b ON s.candidate_url=b.url WHERE candidate_source='stored_url_key_alias'""")
r['bill_mismatch']=rows(c,"SELECT * FROM selected WHERE contains(target_url,'/hr-4824') OR contains(target_url,'/hr-4755')")
dump('followup-results.json',r);print(json.dumps({k:v for k,v in r.items() if k not in ('aliases','alias_key_pairs','bill_mismatch')},indent=2))
