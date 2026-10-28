-- Reduce repeated fetches before unnesting a page's links.
SELECT encode(c.sha256,'hex') AS page_body,c.context_url,c.member_path,
 min(arrow_cast(cast(c.retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS first_good_at,
 max(arrow_cast(cast(c.retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS last_good_at
FROM good_fetches c JOIN page_facts p ON c.sha256=p.body_sha AND p.status='completed'
LEFT JOIN placeholders h ON c.sha256=h.sha256
LEFT JOIN record_roles r USING(receipt_key,receipt_line,capture_index)
WHERE h.sha256 IS NULL AND NOT coalesce(r.format='xml' AND r.record_role='listing',false)
GROUP BY c.sha256,c.context_url,c.member_path
