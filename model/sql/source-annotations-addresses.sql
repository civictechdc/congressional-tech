-- A member's source URL is null; its container remains an attributable address.
WITH addresses AS (
 SELECT source_id,source_url AS url,false AS publisher FROM source_files WHERE source_url IS NOT NULL
 UNION SELECT source_id,context_url AS url,false AS publisher FROM capture_source_contexts WHERE context_url IS NOT NULL
 UNION SELECT source_id,context_url AS url,true AS publisher FROM publisher_links WHERE context_url IS NOT NULL
), distinct_urls AS (
 SELECT url,
  (regexp_match(url,'(?i)^https?://(?:www[.])?(?:govinfo[.]gov|gpo[.]gov)/(?:content/)?pkg/([^/?#]+)/'))[1] AS package_id,
  coalesce((regexp_match(url,'(?i)^https?://docs[.]house[.]gov/meetings/[^/]+/[^/]+/[0-9]{8}/(?:HHRG|HMKP|HMTG)?([0-9]+)(?:/|$)'))[1],
  (regexp_match(url,'(?i)^https?://(?:www[.])?congress[.]gov/[0-9]+/meeting/(?:house|senate|joint)/([0-9]+)(?:/|$)'))[1]) AS meeting_key,
  CASE WHEN regexp_like(url,'(?i)^https?://docs[.]house[.]gov/meetings/') THEN 'house'
  ELSE (regexp_match(url,'(?i)^https?://(?:www[.])?congress[.]gov/[0-9]+/meeting/(house|senate|joint)/'))[1] END AS chamber
 FROM (SELECT DISTINCT url FROM addresses)
)
SELECT a.source_id,a.url,a.publisher,u.package_id,u.meeting_key,u.chamber
FROM addresses a JOIN distinct_urls u USING(url)
