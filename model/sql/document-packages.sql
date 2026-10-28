-- Source/container URL identifiers precede every saved filename-reading fallback.
WITH candidates AS (
 SELECT DISTINCT s.component,s.saved_rank,a.package_id FROM saved_files s
 JOIN source_annotation_addresses a ON s.source_id=a.source_id
 WHERE NOT a.publisher AND a.package_id IS NOT NULL
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY component ORDER BY saved_rank,package_id) AS selected FROM candidates
)
SELECT c.component,r.package_id FROM (SELECT DISTINCT component FROM saved_files) c
LEFT JOIN ranked r ON c.component=r.component AND r.selected=1
