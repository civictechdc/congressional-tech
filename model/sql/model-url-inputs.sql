SELECT DISTINCT encode(sha256(json_array(url)),'hex') AS input_id,url FROM (
 SELECT url FROM source_addresses
 UNION SELECT context_url FROM capture_source_contexts WHERE outcome NOT IN ('reference','saved-record')
 UNION SELECT target_url FROM resolved_links UNION SELECT original_url FROM current_recoveries
 UNION SELECT published_url FROM archive_member_addresses
 -- A meeting record's doc-url is the publisher's literal, like a link href (link-targets): one
 -- that is no http(s) address ('mailto:https://…', 'ttps://…', '/https://…') stays an unresolved
 -- mention, as those same literals do in reference rows (fixtures/reference-sources.json).
 UNION SELECT url FROM meeting_document_urls WHERE regexp_like(url_resolve(url,cast(NULL AS VARCHAR)),'^https?://')
 UNION SELECT unnest(make_array(requested_url,url)) FROM captures
 WHERE mode='fetch' AND outcome NOT IN ('reference','saved-record')
) WHERE url IS NOT NULL AND trim(url)<>'' AND url NOT LIKE 'http://File URL path:%'
