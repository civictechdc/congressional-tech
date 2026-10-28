WITH targets AS (
 SELECT l.*,k.url_key FROM resolved_links l JOIN model_url_keys k ON l.target_url=k.url WHERE k.error IS NULL
), matches AS (
 SELECT t.*,c.source_id FROM targets t JOIN copy_url_keys c ON t.url_key=c.url_key
 WHERE t.target_member_path IS NULL
 UNION ALL
 SELECT t.*,e.source_id FROM targets t JOIN source_endpoints e ON t.url_key=e.endpoint_key
 WHERE (t.target_member_path IS NOT NULL AND t.target_member_path=e.member_path)
    OR (t.target_member_path IS NULL AND e.member_path IS NOT NULL)
)
SELECT DISTINCT *,json_array(context_url,member_path) AS context FROM matches
