SELECT CASE WHEN t.targets=1 THEN t.doc_key WHEN t.original_targets=1 THEN t.original_doc_key END AS doc_key,
 r.recovery_key,r.original_url,r.kind,arrow_cast(decode(r.body_hex,'hex'),'FixedSizeBinary(32)') AS body,
 CASE WHEN regexp_like(r.body_key,'[.]pdf$') THEN '.pdf' WHEN regexp_like(r.body_key,'[.]gz$') THEN '.gz' ELSE '' END AS suffix,
 s.bytes,cast(NULL AS DATE) AS imported_at,r.recovered_url,cast(NULL AS VARCHAR) AS identity_note,
 r.format,r.body_hex,r.body_key
FROM seed_recovery_candidates r JOIN seed_recovery_targets t USING(recovery_key)
LEFT JOIN seed_sizes s ON r.body_key=s.body_key
WHERE t.targets=1 OR t.original_targets=1
