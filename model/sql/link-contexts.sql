-- Resolve the document base once per distinct body/address/member context.
WITH contexts AS (
 SELECT DISTINCT page_body,context_url,member_path,base_href FROM link_inputs
), origins AS (
 SELECT *,CASE WHEN member_path IS NULL THEN context_url
 ELSE 'https://archive.invalid/'||replace(replace(replace(member_path,'%','%25'),'#','%23'),'?','%3F') END AS origin FROM contexts
)
SELECT *,coalesce(url_resolve(nullif(base_href,''),origin),origin) AS resolved_base,
 member_path IS NOT NULL AND (base_href IS NULL OR base_href='' OR
 NOT regexp_like(base_href,'^[A-Za-z][A-Za-z0-9+.-]*:|^//')) AS member_base
FROM origins
