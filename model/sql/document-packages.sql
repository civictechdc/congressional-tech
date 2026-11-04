-- A document's package is one that any of its copies names, never only the saved copy's: a source or
-- container GovInfo address first (member URL order), then a copy's own GovInfo-form filename
-- (source-annotations-final.sql), the earliest-fetched copy first, so a newer copy never renames it.
WITH candidates AS (
 SELECT DISTINCT s.component,1 AS evidence,s.saved_rank,
  arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))') AS first_fetched,a.package_id FROM saved_files s
 JOIN source_annotation_addresses a ON s.source_id=a.source_id
 WHERE NOT a.publisher AND a.package_id IS NOT NULL
 UNION ALL
 SELECT s.component,2 AS evidence,0 AS saved_rank,
  arrow_cast(s.first_fetched,'Timestamp(Microsecond, Some("UTC"))') AS first_fetched,a.package_id FROM saved_files s
 JOIN source_annotations a ON s.source_id=a.source_id
 WHERE a.package_id IS NOT NULL
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY component ORDER BY evidence,saved_rank,first_fetched NULLS LAST,package_id) AS selected FROM candidates
)
SELECT c.component,r.package_id FROM (SELECT DISTINCT component FROM saved_files) c
LEFT JOIN ranked r ON c.component=r.component AND r.selected=1
