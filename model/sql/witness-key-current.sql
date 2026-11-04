-- The published witness rows in the shape witness_key_priors is matched on (ct-kb4w). Its own step:
-- witness_key_map reads it in three joins.
SELECT
 w.witness_key,
 w.occasion,
 w.source,
 coalesce(w.package_id,'') AS package_key,
 w.record_sha_hex,
 w.source_locator,
 w.name_key,
 w.position,
 w.organization,
 w.on_behalf_of,
 w.location,
 w.panel,
 w.witness_type,
 w.bioguide_id,
 encode(sha256(json_array(w.name_key,w.position,w.organization,w.on_behalf_of,w.location,w.panel,w.witness_type,w.bioguide_id)),'hex') AS signature,
 row_number() OVER (
  PARTITION BY w.occasion,w.source,coalesce(w.package_id,''),w.name_key,w.position,w.organization,w.on_behalf_of,w.location,w.panel,w.witness_type,w.bioguide_id
  ORDER BY w.ordinal) AS repeat_rank,
 p.family,
 p.given,
 p.given_canon
FROM appearance_records_resolved w
LEFT JOIN appearance_people p ON p.record_sha_hex=w.record_sha_hex AND p.source=w.source AND p.ordinal=w.ordinal
