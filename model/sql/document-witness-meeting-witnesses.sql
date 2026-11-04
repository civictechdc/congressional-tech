SELECT DISTINCT
 w.event_id,
 w.witness_key,
 regexp_replace(lower(p.family),'[^a-z0-9]','','g') AS norm_family,
 regexp_replace(lower(p.family),'[^a-z0-9]','','g')||
  substr(regexp_replace(lower(coalesce(p.given,'')),'[^a-z0-9]','','g'),1,1) AS norm_family_init
FROM appearance_records_resolved w
LEFT JOIN witness_precedence wp ON wp.witness_key=w.witness_key
JOIN appearance_people p ON p.record_sha_hex=w.record_sha_hex
 AND p.source=w.source AND p.ordinal=w.ordinal
WHERE w.event_id IS NOT NULL
 AND w.occasion='meeting:'||cast(w.event_id AS VARCHAR)
 AND wp.superseded_by IS NULL
 AND NOT p.statement
 AND p.family IS NOT NULL
