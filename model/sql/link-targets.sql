-- Resolve distinct literal/context pairs, then reattach link ordinals and publisher facts.
WITH instances AS (
 SELECT DISTINCT page_body,context_url,member_path,base_href,href FROM link_inputs
), parsed AS (
 SELECT l.*,p.repair_matches,p.split_position,p.target_literal,c.member_base,
 url_resolve(p.target_literal,c.resolved_base) AS resolved,
 regexp_replace(regexp_replace(p.target_literal,'[\t\n\r]','','g'),'^[\x00-\x20]+','') AS target_spelling
 FROM instances l JOIN link_contexts c ON (l.page_body=c.page_body)
 AND (l.context_url=c.context_url) AND (l.member_path IS NOT DISTINCT FROM c.member_path)
 AND (l.base_href IS NOT DISTINCT FROM c.base_href)
 JOIN link_parts p ON l.href=p.href
), resolved AS (
 SELECT *,member_base AND regexp_like(resolved,'^https://archive[.]invalid/')
 AND NOT regexp_like(target_spelling,'(?i)^(?:https?:)?[\\/]{2}') AS member_target FROM parsed
)
SELECT r.*,CASE WHEN member_target THEN context_url ELSE resolved END AS target_url,
 CASE WHEN member_target THEN percent_decode_utf8(regexp_replace(split_part(split_part(resolved,'?',1),'#',1),
 '^https://archive[.]invalid/','')) END AS target_member_path,
 CASE WHEN repair_matches>1 THEN 'repair_conflict'
 WHEN resolved IS NULL OR NOT regexp_like(resolved,'^https?://') THEN 'invalid_target'
 WHEN repair_matches=1 AND f.id IS NULL THEN 'invalid_repair' END AS target_error
FROM resolved r LEFT JOIN file_shapes f ON f.id='extensions' AND regexp_like(r.resolved,f.pattern)
