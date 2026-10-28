SELECT DISTINCT encode(sha256(json_array(url)),'hex') AS input_id,url FROM (
 SELECT url FROM source_addresses UNION SELECT context_url FROM capture_sources
 UNION SELECT target_url FROM resolved_links UNION SELECT original_url FROM current_recoveries
 UNION SELECT requested_url FROM captures WHERE mode='fetch'
 UNION SELECT url FROM captures WHERE mode='fetch'
) WHERE url IS NOT NULL
