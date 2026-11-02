-- The shared per-attempt body-eligibility predicate; imports qualify as fetches, but not as capture dates.
-- An archive member has no completeness of its own: its exact container attempt must be complete and
-- expanded. The container key is de-duplicated, so repeated container rows cannot fan a member out.
WITH expanded_containers AS (
 SELECT DISTINCT receipt_key,receipt_line FROM capture_evidence
 WHERE member_path IS NULL AND expansion='expanded' AND mode='fetch' AND complete
  AND outcome IN ('stored','unchanged') AND http_status BETWEEN 200 AND 299
)
SELECT * FROM capture_evidence WHERE mode='fetch' AND complete
 AND outcome IN ('stored','unchanged') AND http_status BETWEEN 200 AND 299
UNION ALL
SELECT c.* FROM expanded_containers x JOIN capture_evidence c ON c.receipt_key=x.receipt_key AND c.receipt_line=x.receipt_line
WHERE c.member_path IS NOT NULL AND c.complete IS NOT TRUE AND c.mode='fetch' AND c.outcome IN ('stored','unchanged')
