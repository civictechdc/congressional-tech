-- DM 7.5 saved-file order chooses the saved body; among that body's source
-- files a named one with an address comes first: the body cannot change, its name can.
WITH ranked AS (
 SELECT m.*,row_number() OVER(PARTITION BY m.component ORDER BY coalesce(p.rank,2147483647),
 CASE WHEN p.rank IS NULL THEN m.format ELSE '' END,coalesce(m.exact_bytes,false) DESC,
 m.first_fetched DESC NULLS LAST,m.body_sha,m.source_id) AS base_rank
 FROM formats p RIGHT JOIN (SELECT * FROM document_members WHERE is_real_file) m
  ON p.kind='preference' AND p.value=m.format
), bodies AS (
 SELECT *,min(base_rank) OVER(PARTITION BY component,body_sha) AS body_rank FROM ranked
)
SELECT * EXCLUDE(base_rank,body_rank),row_number() OVER(PARTITION BY component
 ORDER BY body_rank,coalesce(filename,'')='',source_url IS NULL,base_rank) AS saved_rank FROM bodies
