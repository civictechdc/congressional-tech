SELECT DISTINCT encode(sha256(json_array(url)),'hex') AS input_id,url FROM (
 SELECT url FROM source_addresses
 UNION SELECT context_url FROM capture_sources WHERE outcome NOT IN ('reference','saved-record')
 UNION SELECT target_url FROM resolved_links UNION SELECT original_url FROM current_recoveries
 UNION SELECT unnest(make_array(requested_url,url)) FROM captures
 WHERE mode='fetch' AND outcome NOT IN ('reference','saved-record')
) WHERE url IS NOT NULL
