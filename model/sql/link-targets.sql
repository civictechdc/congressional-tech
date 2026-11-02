-- Resolve distinct literal/context pairs, then reattach link ordinals and publisher facts.
-- Contexts are keyed by link_contexts.context_id (same digest of the same four keys).
WITH instances AS (
 SELECT DISTINCT sha256(json_array(page_body,context_url,member_path,base_href)) AS context_id,href FROM link_inputs
), parsed AS (
 SELECT l.context_id,l.href,c.context_url,p.repair_matches,p.split_position,p.target_literal,c.member_base,
 url_resolve(p.target_literal,c.resolved_base) AS resolved,
 regexp_replace(regexp_replace(p.target_literal,'[\t\n\r]','','g'),'^[\x00-\x20]+','') AS target_spelling
 FROM (SELECT * FROM link_contexts WHERE page_body IS NOT NULL AND context_url IS NOT NULL) c JOIN instances l
 ON l.context_id=c.context_id
 JOIN (SELECT * FROM link_parts WHERE href IS NOT NULL) p ON (l.href IS NOT DISTINCT FROM p.href)
), resolved AS (
 SELECT *,member_base AND regexp_like(resolved,'^https://archive[.]invalid/')
 AND NOT regexp_like(target_spelling,'(?i)^(?:https?:)?[\\/]{2}') AS member_target FROM parsed
)
SELECT r.context_id,r.href,r.split_position,r.target_literal,
 CASE WHEN member_target THEN context_url ELSE resolved END AS target_url,
 CASE WHEN member_target THEN percent_decode_utf8(regexp_replace(split_part(split_part(resolved,'?',1),'#',1),
 '^https://archive[.]invalid/','')) END AS target_member_path,
 CASE WHEN repair_matches>1 THEN 'repair_conflict'
 WHEN resolved IS NULL OR NOT regexp_like(resolved,'^https?://') THEN 'invalid_target'
 WHEN repair_matches=1 AND f.id IS NULL THEN 'invalid_repair' END AS target_error
FROM file_shapes f RIGHT JOIN resolved r ON f.id='extensions' AND regexp_like(r.resolved,f.pattern)
