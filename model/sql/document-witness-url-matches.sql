SELECT m.component,w.witness_key
FROM document_members m
JOIN copy_url_keys ck ON m.source_id=ck.source_id
JOIN document_witness_url_keys w ON ck.url_key=w.url_key
WHERE NOT EXISTS (SELECT 1 FROM document_witness_chrg_components c WHERE c.component=m.component)
UNION
SELECT r.component,w.witness_key
FROM saved_recoveries r
JOIN recovery_original_keys rk ON r.id=rk.recovery_id
JOIN document_witness_url_keys w ON rk.url_key=w.url_key
WHERE NOT EXISTS (SELECT 1 FROM document_witness_chrg_components c WHERE c.component=r.component)
UNION
-- A vetted Banking hearing page supplies its own roster as well as links
-- to statements. Require the exact source bytes and address so a different
-- capture of the same URL cannot inherit this occurrence. If the selected
-- occurrence uses an alias, use the hearing address from its body/event link.
SELECT m.component,w.witness_key
FROM (
 SELECT a.witness_key,a.record_sha_hex,
  coalesce(CASE WHEN regexp_like(a.page_url,'(?i)^https?://(?:www[.])?banking[.]senate[.]gov/hearings/')
   THEN a.page_url END,l.banking_hearing_url) AS hearing_url
 FROM appearance_records_resolved a
 LEFT JOIN senate_page_meeting_links l ON l.record_sha_hex=a.record_sha_hex AND l.event_id=a.event_id
 WHERE a.source='senate_page' AND a.event_id IS NOT NULL
  AND regexp_like(a.page_url,'(?i)^https?://(?:www[.])?banking[.]senate[.]gov/')
) w
JOIN source_files sf ON sf.body_sha=w.record_sha_hex AND sf.source_url=w.hearing_url
JOIN document_members m ON m.source_id=sf.source_id
WHERE NOT EXISTS (SELECT 1 FROM document_witness_chrg_components c WHERE c.component=m.component)
