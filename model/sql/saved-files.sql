-- DM 7.5 saved-file order chooses the saved body; among that body's source
-- files a named one comes first, otherwise saved-file order holds (a ZIP
-- member, whose source has no address of its own, is a first-class copy), and a
-- source with neither an address nor a member path comes last, so the published
-- address never goes blank. The body cannot change, only these rows' places. Running windows only, so the
-- plan streams (no whole-partition WindowAggExec).
WITH ranked AS (
 SELECT m.*,row_number() OVER w AS base_rank,first_value(m.body_sha) OVER w AS saved_body
 FROM formats p RIGHT JOIN (SELECT * FROM document_members WHERE is_real_file) m
  ON p.kind='preference' AND p.value=m.format
 WINDOW w AS (PARTITION BY m.component ORDER BY coalesce(p.rank,2147483647),
 CASE WHEN p.rank IS NULL THEN m.format ELSE '' END,coalesce(m.exact_bytes,false) DESC,
 m.first_fetched DESC NULLS LAST,m.body_sha,m.source_id)
)
SELECT * EXCLUDE(base_rank,saved_body,is_saved_body),row_number() OVER(PARTITION BY component
 ORDER BY is_saved_body DESC,is_saved_body AND coalesce(filename,'')='',
  is_saved_body AND source_url IS NULL AND NOT coalesce(archive_member,false),base_rank) AS saved_rank
FROM (SELECT *,body_sha IS NOT DISTINCT FROM saved_body AS is_saved_body FROM ranked)
