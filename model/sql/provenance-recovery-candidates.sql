-- Capture identity is never replaced by a provenance decision's identity.
SELECT c.receipt_key,c.receipt_line,c.capture_index,
 encode(sha256(json_array(c.receipt_key,c.receipt_line,c.capture_index)),'hex') AS recovery_id,
 coalesce(d.id,'row:'||encode(sha256(json_array(c.receipt_key,c.receipt_line,c.capture_index)),'hex')) AS id,
 d.id AS decision_id,c.original_url,encode(c.sha256,'hex') AS body_sha,c.bytes,c.imported_at,
 coalesce(c.recovered_url,d.recovered_url) AS recovered_url,d.recovered_filename,d.identity_note,
 CASE WHEN d.kind='rejected' THEN 'rejected'
 WHEN c.recovery_category IS NOT NULL THEN category.kind ELSE coalesce(d.kind,basis.kind,'recovered_document') END AS kind
FROM captures c LEFT JOIN remaining_recovery_decisions d
 ON encode(c.sha256,'hex')=lower(d.body_sha256) AND c.original_url=d.original_url
LEFT JOIN recovery_kinds category ON c.recovery_category=category.category
LEFT JOIN recovery_kinds basis ON basis.category IS NULL AND c.match_basis=basis.match_basis
WHERE c.mode='retained_import' AND c.sha256 IS NOT NULL
