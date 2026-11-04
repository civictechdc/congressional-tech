-- Every witness key that a held observation produces but this release does not publish (ct-kb4w): a
-- superseded body or capture context at an occasion, the same occurrence filed under its print or page
-- before a meeting link held it (fallback_occasion), and the key hashed before a capture context was
-- bound (free_context_key). witness-occurrence-v2 is unchanged; these are the keys earlier releases
-- could have published. A key appears once per context of its body that produces it, filed under the
-- occasion its observation holds now.
WITH occurrences AS (
 SELECT
  o.occasion,
  o.fallback_occasion,
  o.source,
  o.record_sha_hex,
  o.context_key,
  o.free_context_key,
  coalesce(o.package_id,'') AS package_key,
  unnest(r.appearances) AS a,
  unnest(range(0,cast(array_length(r.appearances) AS BIGINT))) AS ordinal
 FROM appearance_observations o
 JOIN selected_appearance_records r ON r.record_sha_hex=o.record_sha_hex AND r.source=o.source
 WHERE o.effective_state='present' AND coalesce(array_length(r.appearances),0)>0
), extracted AS (
 SELECT
  occasion,
  fallback_occasion,
  source,
  record_sha_hex,
  context_key,
  free_context_key,
  package_key,
  ordinal,
  coalesce(nullif(trim(a['source_locator']),''),source||':witness['||cast(ordinal+1 AS VARCHAR)||']') AS source_locator,
  nullif(trim(a['name_key']),'') AS name_key,
  nullif(trim(a['position']),'') AS position,
  nullif(trim(a['organization']),'') AS organization,
  nullif(trim(a['on_behalf_of']),'') AS on_behalf_of,
  nullif(trim(a['location']),'') AS location,
  nullif(trim(a['panel']),'') AS panel,
  nullif(trim(a['witness_type']),'') AS witness_type,
  nullif(trim(a['bioguide_id']),'') AS bioguide_id
 FROM occurrences
), ranked AS (
 -- A list that names the same person twice pairs its repeats in order with the current list's repeats.
 SELECT *,
  encode(sha256(json_array(name_key,position,organization,on_behalf_of,location,panel,witness_type,bioguide_id)),'hex') AS signature,
  row_number() OVER (
   PARTITION BY record_sha_hex,source,occasion,context_key,name_key,position,organization,on_behalf_of,location,panel,witness_type,bioguide_id
   ORDER BY ordinal) AS repeat_rank
 FROM extracted
), variants AS (
 -- A variant equal to an earlier one is left out; the free variants of one body still repeat across its
 -- contexts, and witness_key_map groups them by key.
 SELECT r.*,unnest(make_array(
   named_struct('occasion',occasion,'context',context_key),
   named_struct('occasion',CASE WHEN fallback_occasion<>occasion THEN fallback_occasion END,'context',context_key),
   named_struct('occasion',CASE WHEN free_context_key<>context_key THEN occasion END,'context',free_context_key),
   named_struct('occasion',CASE WHEN fallback_occasion<>occasion AND free_context_key<>context_key THEN fallback_occasion END,
    'context',free_context_key))) AS v
 FROM ranked r
), keyed AS (
 SELECT
  substr(encode(sha256(json_array('witness-occurrence-v2',v['occasion'],source,record_sha_hex,source_locator,v['context'])),'hex'),1,16) AS old_key,
  occasion,source,package_key,record_sha_hex,source_locator,ordinal,name_key,position,organization,on_behalf_of,location,panel,
  witness_type,bioguide_id,signature,repeat_rank
 FROM variants
 WHERE v['occasion'] IS NOT NULL
), unpublished AS (
 SELECT k.*
 FROM (SELECT witness_key FROM appearance_records_resolved) w
 RIGHT ANTI JOIN keyed k ON w.witness_key=k.old_key
)
SELECT k.*,p.family,p.given,p.given_canon
FROM unpublished k
LEFT JOIN appearance_people p ON p.record_sha_hex=k.record_sha_hex AND p.source=k.source AND p.ordinal=k.ordinal
