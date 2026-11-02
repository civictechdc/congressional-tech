SELECT l.*,t.split_position,t.target_literal,t.target_url,t.target_member_path
FROM (SELECT * FROM link_errors WHERE href IS NOT NULL) e RIGHT ANTI JOIN (
 (SELECT * FROM link_targets WHERE href IS NOT NULL) t JOIN link_inputs l
 ON sha256(json_array(l.page_body,l.context_url,l.member_path,l.base_href))=t.context_id
 AND (l.href IS NOT DISTINCT FROM t.href)
) ON e.context_id=t.context_id AND (e.href IS NOT DISTINCT FROM t.href)
WHERE t.target_error IS NULL
