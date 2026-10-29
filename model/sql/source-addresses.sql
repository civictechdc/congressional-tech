-- Top-level copy URLs include requested addresses only for good fetches.
SELECT DISTINCT s.source_id,s.source_url AS url,cast(NULL AS VARCHAR) AS member_path
FROM source_files s JOIN capture_source_contexts c ON s.source_id=c.source_id
LEFT JOIN source_url_keys uk ON uk.url=s.source_url
WHERE c.member_path IS NULL AND s.source_url IS NOT NULL
 AND (c.outcome NOT IN ('reference','saved-record') OR s.body_sha IS NOT NULL)
 AND (s.body_sha IS NOT NULL OR uk.error IS NULL)
UNION
SELECT DISTINCT c.source_id,g.requested_url AS url,cast(NULL AS VARCHAR) AS member_path
FROM good_fetches g JOIN capture_source_contexts c USING(receipt_key,receipt_line,capture_index)
WHERE c.member_path IS NULL AND g.requested_url IS NOT NULL
