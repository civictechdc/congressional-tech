WITH fidelity AS (
 SELECT source_id,bool_or(exact_bytes) AS exact_bytes FROM source_files GROUP BY source_id
), ranked AS (
 SELECT m.*,row_number() OVER(PARTITION BY m.component ORDER BY coalesce(p.rank,2147483647),
 CASE WHEN p.rank IS NULL THEN m.format ELSE '' END,coalesce(f.exact_bytes,false) DESC,
 m.first_fetched DESC NULLS LAST,m.body_sha,m.source_id) AS saved_rank
 FROM fidelity f RIGHT JOIN (
  formats p RIGHT JOIN document_members m ON p.kind='preference' AND p.value=m.format
 ) USING(source_id) WHERE m.is_real_file
)
SELECT * FROM ranked
