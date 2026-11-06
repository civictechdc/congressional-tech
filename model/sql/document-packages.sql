-- GovInfo source and container addresses outrank filenames. A reviewed PDF
-- can supply a missing package when the document holds those exact bytes.
-- All non-authoritative bill candidates must agree on the measure itself.
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
 UNION ALL
 SELECT DISTINCT pdf.component,3 AS evidence,0 AS saved_rank,
  arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))') AS first_fetched,e.package_id
 FROM bill_package_evidence e
 JOIN saved_files pdf ON e.pdf_sha=pdf.body_sha AND pdf.format='pdf'
 WHERE e.package_disposition='support'
), ranked AS (
 -- Scan from least to most preferred so the last row has both the winning
 -- package and the complete bill range. Every candidate has a package ID.
 SELECT *,
  lead(package_id) OVER w AS next_package,
  min(bill_measure) OVER w AS min_bill_measure,
  max(bill_measure) OVER w AS max_bill_measure
 FROM (
  SELECT *,CASE WHEN evidence>1 AND starts_with(package_id,'BILLS-')
   THEN (regexp_match(package_id,'^(BILLS-[0-9]+[a-z]+[0-9]+)'))[1] END AS bill_measure
  FROM candidates
 )
 WINDOW w AS (PARTITION BY component
  ORDER BY evidence DESC,saved_rank DESC,first_fetched DESC NULLS FIRST,package_id DESC
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
), preferred AS (
 SELECT component,package_id,
  coalesce(evidence>1 AND starts_with(package_id,'BILLS-') AND min_bill_measure<>max_bill_measure,false) AS bill_package_conflict
 FROM ranked WHERE next_package IS NULL
)
SELECT c.component,CASE WHEN NOT p.bill_package_conflict AND NOT coalesce(bd.package_withheld,false) THEN p.package_id END AS package_id,
 coalesce(p.bill_package_conflict,false) AS bill_package_conflict
FROM (SELECT DISTINCT component FROM saved_files) c
LEFT JOIN preferred p ON c.component=p.component
LEFT JOIN document_bill_decisions bd ON c.component=bd.component
