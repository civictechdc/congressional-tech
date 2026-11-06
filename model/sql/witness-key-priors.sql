-- Every witness key that a held observation produces but this release does not publish (ct-kb4w): a
-- superseded body or capture context at an occasion, the same occurrence filed under its print or page
-- before a meeting link held it (fallback_occasion), and the key hashed before a capture context was
-- bound (free_context_key). witness-occurrence-v2 is unchanged; these are the keys earlier releases
-- could have published. Vetted print links also retain meeting keys after a multi-day print's
-- witnesses move back to package scope. Matching still uses the observation's current occasion.
WITH historical_meeting_occasions AS (
 SELECT package_id,array_agg('meeting:'||cast(event_id AS VARCHAR) ORDER BY event_id) AS occasions
 FROM package_meeting_links
 WHERE event_id IS NOT NULL
 GROUP BY package_id
), occurrences AS (
 SELECT
  o.occasion,
  o.fallback_occasion,
  o.source,
  o.record_sha_hex,
  o.context_key,
  o.free_context_key,
  h.occasions AS historical_occasions,
  coalesce(o.package_id,'') AS package_key,
  unnest(r.appearances) AS a,
  unnest(range(0,cast(array_length(r.appearances) AS BIGINT))) AS ordinal
 FROM historical_meeting_occasions h
 RIGHT JOIN appearance_observations o ON o.source='mods' AND o.package_id=h.package_id
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
  historical_occasions,
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
), occasion_variants AS (
 SELECT r.*,unnest(array_distinct(array_concat(
  make_array(occasion,fallback_occasion),coalesce(historical_occasions,make_array(cast(NULL AS VARCHAR)))
 ))) AS prior_occasion
 FROM ranked r
), variants AS (
 -- Each supported occasion uses the original bound and free capture contexts. Repeated people
 -- retain their source locators and repeat ranks; the existing matcher decides their successors.
 SELECT r.*,unnest(make_array(
   named_struct('occasion',prior_occasion,'context',context_key),
   named_struct('occasion',CASE WHEN free_context_key<>context_key THEN prior_occasion END,'context',free_context_key))) AS v
 FROM occasion_variants r
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
