SELECT d.document_id AS doc_key,r.saved_rank AS recovery_key,
 r.original_url,r.kind,arrow_cast(decode(r.body_sha,'hex'),'FixedSizeBinary(32)') AS body,b.suffix,
 r.bytes,cast(r.imported_at AS DATE) AS imported_at,r.recovered_url,r.identity_note
FROM saved_recoveries r JOIN document_identities d USING(component)
JOIN body_evidence b ON r.body_sha=b.body_sha
