-- Each member's document also answers to its ZIP's public link. A ZIP holding several
-- documents resolves to the first; its URL stays on each member's sources row.
WITH containers AS (
 SELECT DISTINCT receipt_key,receipt_line,lower(encode(sha256,'hex')) AS body_sha FROM record_roles WHERE record_role='archive'
)
SELECT DISTINCT m.source_id,z.body_sha
FROM containers z JOIN capture_source_contexts m ON m.receipt_key=z.receipt_key AND m.receipt_line=z.receipt_line
WHERE m.member_path IS NOT NULL
