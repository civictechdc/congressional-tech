WITH targets AS (
 -- A link back to its own page (a fragment such as "#main" or "#", or the page's own address:
 -- skip, share, print and back-to-top links) is navigation, never a listing of that page.
 SELECT l.*,k.url_key FROM model_url_keys c RIGHT JOIN (
  model_url_keys k JOIN resolved_links l ON l.target_url=k.url
 ) ON c.url=l.context_url
 WHERE k.error IS NULL
  AND NOT ((k.url_key IS NOT DISTINCT FROM c.url_key) AND (l.target_member_path IS NOT DISTINCT FROM l.member_path))
), matches AS (
 SELECT t.*,c.source_id FROM copy_url_keys c JOIN targets t ON t.url_key=c.url_key
 WHERE t.target_member_path IS NULL
 UNION ALL
 SELECT t.*,e.source_id FROM source_endpoints e JOIN targets t ON t.url_key=e.endpoint_key
 WHERE (t.target_member_path IS NOT NULL AND t.target_member_path=e.member_path)
    OR (t.target_member_path IS NULL AND e.member_path IS NOT NULL)
)
SELECT DISTINCT *,json_array(context_url,member_path) AS context FROM matches
