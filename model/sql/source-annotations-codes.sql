SELECT source_id,unnest(committee_code) AS code FROM source_filename_readings WHERE status='completed'
UNION
SELECT DISTINCT c.source_id,upper(sc.system_code) AS code
FROM capture_source_contexts c
JOIN spicy_committees sc ON sc.parent_system_code IS NULL AND lower(sc.system_code)<>'jjec00'
 AND regexp_like(coalesce(sc.website_url,''),'(?i)^https?://(?:www[.])?[a-z0-9-]+[.]senate[.]gov')
 AND lower((regexp_match(coalesce(c.context_url,''),'(?i)^https?://(?:www[.])?([a-z0-9-]+)[.]senate[.]gov'))[1])=
     lower((regexp_match(sc.website_url,'(?i)^https?://(?:www[.])?([a-z0-9-]+)[.]senate[.]gov'))[1])

