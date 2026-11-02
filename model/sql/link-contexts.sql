-- Resolve the document base once per distinct body/address/member context. context_id is the
-- null-preserving digest of those four keys, so link_targets, link_errors and resolved_links
-- group and join on one 32-byte key instead of four wide strings.
WITH contexts AS (
 SELECT DISTINCT page_body,context_url,member_path,base_href FROM link_inputs
), origins AS (
 SELECT *,sha256(json_array(page_body,context_url,member_path,base_href)) AS context_id,
 CASE WHEN member_path IS NULL THEN context_url
 ELSE 'https://archive.invalid/'||replace(replace(replace(member_path,'%','%25'),'#','%23'),'?','%3F') END AS origin
 FROM contexts
), bases AS (
 SELECT *,coalesce(url_resolve(nullif(base_href,''),origin),origin) AS resolved_base,
 regexp_replace(regexp_replace(coalesce(base_href,''),'[\t\n\r]','','g'),'^[\x00-\x20]+','') AS base_spelling
 FROM origins
)
SELECT *,member_path IS NOT NULL AND regexp_like(resolved_base,'^https://archive[.]invalid/')
 AND NOT regexp_like(base_spelling,'(?i)^(?:https?:)?[\\/]{2}') AS member_base FROM bases
