-- The containers whose members count: a complete, expanded good fetch, or a retained import of
-- a ZIP byte-identical by digest to a good download. Keys are distinct, so rows cannot fan out.
WITH good_bodies AS (
 SELECT DISTINCT sha256 FROM capture_evidence WHERE member_path IS NULL AND sha256 IS NOT NULL AND mode='fetch' AND complete
  AND outcome IN ('stored','unchanged') AND http_status BETWEEN 200 AND 299
)
SELECT DISTINCT c.receipt_key,c.receipt_line,c.sha256
FROM good_bodies g JOIN capture_evidence c ON c.sha256=g.sha256
WHERE c.member_path IS NULL AND c.expansion='expanded' AND c.mode IN ('fetch','retained_import') AND c.complete
 AND c.outcome IN ('stored','unchanged') AND c.http_status BETWEEN 200 AND 299
