-- Materialize the eligible Senate records once for capture URLs, page facts and the context fallback.
SELECT DISTINCT r.record_sha_hex,r.context_url,
 arrow_cast(decode(r.record_sha_hex,'hex'),'FixedSizeBinary(32)') AS sha256
FROM (SELECT DISTINCT record_sha_hex FROM appearance_people WHERE source='senate_page') ap
JOIN selected_appearance_records r
 ON ap.record_sha_hex=r.record_sha_hex
WHERE r.source='senate_page' AND r.status='completed'
 AND coalesce(nullif(trim(r.collection_state),''),'present')='present'
