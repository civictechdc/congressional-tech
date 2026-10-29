-- Top-level copy URLs include requested addresses only for good fetches.
SELECT DISTINCT c.source_id,c.source_url AS url,cast(NULL AS VARCHAR) AS member_path
FROM capture_sources c WHERE c.member_path IS NULL AND c.source_url IS NOT NULL
 AND (c.outcome NOT IN ('reference','saved-record') OR c.body_sha IS NOT NULL)
UNION
SELECT DISTINCT c.source_id,c.requested_url,cast(NULL AS VARCHAR)
FROM good_fetches g JOIN capture_sources c USING(receipt_key,receipt_line,capture_index)
WHERE c.member_path IS NULL AND c.requested_url IS NOT NULL
