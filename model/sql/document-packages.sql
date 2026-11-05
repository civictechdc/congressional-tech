-- GovInfo source and container addresses outrank filenames. A filename can
-- identify a bill package only when the copies agree on the bill itself.
-- Different versions of the same bill keep the existing filename order.
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
 SELECT *,
  row_number() OVER(PARTITION BY component ORDER BY evidence,saved_rank,first_fetched NULLS LAST,package_id) AS selected,
  min(bill_measure) OVER(PARTITION BY component) AS min_bill_measure,
  max(bill_measure) OVER(PARTITION BY component) AS max_bill_measure
 FROM (
  SELECT *,CASE WHEN evidence=2 AND starts_with(package_id,'BILLS-')
   THEN (regexp_match(package_id,'^(BILLS-[0-9]+[a-z]+[0-9]+)'))[1] END AS bill_measure
  FROM candidates
 )
), preferred AS (
 SELECT component,package_id,
  coalesce(evidence=2 AND starts_with(package_id,'BILLS-') AND min_bill_measure<>max_bill_measure,false) AS bill_package_conflict
 FROM ranked WHERE selected=1
)
SELECT c.component,CASE WHEN NOT p.bill_package_conflict THEN p.package_id END AS package_id,
 coalesce(p.bill_package_conflict,false) AS bill_package_conflict
FROM (SELECT DISTINCT component FROM saved_files) c
LEFT JOIN preferred p ON c.component=p.component
