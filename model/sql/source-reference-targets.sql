-- One owned body per normalized address. Never choose between body editions.
-- Ordered first values select the same existing name/address pair, including
-- when repeated captures or aliases give that body more than one source ID.
SELECT k.url_key,max(n.body_sha) AS body_sha,
 first_value(n.filename ORDER BY n.filename,n.source_url) AS filename,
 first_value(n.source_url ORDER BY n.filename,n.source_url) AS source_url
FROM source_url_keys k JOIN capture_source_names n ON k.url=n.source_url
WHERE k.error IS NULL AND k.url_key IS NOT NULL AND n.is_real_file
 AND n.sha256 IS NOT NULL AND n.member_path IS NULL
GROUP BY k.url_key HAVING count(DISTINCT n.body_sha)=1
