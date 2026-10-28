SELECT l.*,t.split_position,t.target_literal,t.target_url,t.target_member_path
FROM link_inputs l JOIN link_targets t ON l.page_body=t.page_body AND l.context_url=t.context_url
 AND (l.member_path IS NOT DISTINCT FROM t.member_path) AND (l.base_href IS NOT DISTINCT FROM t.base_href)
 AND l.href=t.href
WHERE t.target_error IS NULL AND NOT EXISTS (
 SELECT 1 FROM link_errors e WHERE e.page_body=t.page_body AND e.context_url=t.context_url
 AND (e.member_path IS NOT DISTINCT FROM t.member_path) AND (e.base_href IS NOT DISTINCT FROM t.base_href)
 AND e.href=t.href)
