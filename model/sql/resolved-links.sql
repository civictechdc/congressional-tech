SELECT l.*,t.split_position,t.target_literal,t.target_url,t.target_member_path
FROM link_inputs l JOIN (SELECT * FROM link_targets WHERE page_body IS NOT NULL AND context_url IS NOT NULL AND href IS NOT NULL) t
 ON (l.page_body IS NOT DISTINCT FROM t.page_body) AND (l.context_url IS NOT DISTINCT FROM t.context_url)
 AND (l.member_path IS NOT DISTINCT FROM t.member_path) AND (l.base_href IS NOT DISTINCT FROM t.base_href)
 AND (l.href IS NOT DISTINCT FROM t.href)
WHERE t.target_error IS NULL AND NOT EXISTS (
 SELECT 1 FROM link_errors e WHERE e.page_body IS NOT NULL AND e.context_url IS NOT NULL AND e.href IS NOT NULL
 AND (e.page_body IS NOT DISTINCT FROM t.page_body) AND (e.context_url IS NOT DISTINCT FROM t.context_url)
 AND (e.member_path IS NOT DISTINCT FROM t.member_path) AND (e.base_href IS NOT DISTINCT FROM t.base_href)
 AND (e.href IS NOT DISTINCT FROM t.href))
