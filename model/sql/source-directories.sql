-- One source may occur in several member directories; retain all memberships.
SELECT DISTINCT c.source_id,
 CASE WHEN c.member_path IS NOT NULL THEN json_array(c.context_url,regexp_replace(c.member_path,'[^/]*$',''))
 ELSE json_array((regexp_match(s.source_url,'^(https?://[^/?#]+)'))[1],
 regexp_replace(coalesce(nullif((regexp_match(s.source_url,'^https?://[^/?#]+([^?#]*)'))[1],''),'/'),'[^/]*$','')) END AS directory_key,
 regexp_replace(s.filename,'[.][^.]*$','') AS stem
FROM capture_source_contexts c JOIN source_files s USING(source_id)
