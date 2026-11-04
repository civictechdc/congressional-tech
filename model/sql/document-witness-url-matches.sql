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
