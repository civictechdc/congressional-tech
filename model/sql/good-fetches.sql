-- The shared per-attempt body-eligibility predicate; imports qualify as fetches, but not as capture dates.
-- An archive member has no completeness of its own: its exact container attempt must be good.
WITH containers AS (
 SELECT DISTINCT receipt_key,receipt_line FROM good_archive_containers
)
SELECT * FROM capture_evidence WHERE mode='fetch' AND complete
 AND outcome IN ('stored','unchanged') AND http_status BETWEEN 200 AND 299
UNION ALL
SELECT c.* FROM containers x JOIN capture_evidence c ON c.receipt_key=x.receipt_key AND c.receipt_line=x.receipt_line
WHERE c.member_path IS NOT NULL AND c.complete IS NOT TRUE AND c.mode IN ('fetch','retained_import') AND c.outcome IN ('stored','unchanged')
