-- A ZIP is how files were captured. Once its contents are captured they are the documents.
WITH member_lines AS (
 SELECT DISTINCT receipt_key,receipt_line FROM capture_evidence WHERE member_path IS NOT NULL
)
SELECT DISTINCT z.sha256 FROM member_lines m JOIN capture_evidence z
 ON z.receipt_key=m.receipt_key AND z.receipt_line=m.receipt_line
WHERE z.member_path IS NULL AND z.expansion='expanded' AND z.sha256 IS NOT NULL
