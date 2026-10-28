SELECT d.document_id AS doc_key,json_array(r.receipt_key,r.receipt_line,r.capture_index) AS recovery_key,
 r.original_url,r.kind,arrow_cast(decode(r.body_sha,'hex'),'FixedSizeBinary(32)') AS body,b.suffix,
 r.bytes,cast(r.imported_at AS DATE) AS imported_at,r.recovered_url,r.identity_note
FROM final_recovery_attachments r JOIN document_identities d USING(component)
JOIN body_evidence b ON r.body_sha=b.body_sha
