-- One source may occur in several member directories; retain all memberships.
SELECT DISTINCT source_id,
 CASE WHEN member_path IS NOT NULL THEN json_array(context_url,regexp_replace(member_path,'[^/]*$',''))
 ELSE json_array((regexp_match(source_url,'^(https?://[^/?#]+)'))[1],
 regexp_replace(coalesce(nullif((regexp_match(source_url,'^https?://[^/?#]+([^?#]*)'))[1],''),'/'),'[^/]*$','')) END AS directory_key,
 regexp_replace(filename,'[.][^.]*$','') AS stem
FROM capture_sources
