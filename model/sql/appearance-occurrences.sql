-- Selected witness occurrences and retained Congress.gov unlisted witnesses (ct-960v, ct-46f3).
-- Computes normalized text columns (name_t, organization_t, position_t), deterministic occ_id, repeat occurrence_ordinal,
-- and new-witness v3_key once so appearance_records_resolved and witness_key_map share a single materialized step.
WITH selected_observations AS (
 -- When the top-ranked source lists witnesses, every source's current body publishes and precedence is
 -- per person, not per source (red-f2): a lower row is superseded only by the same person from a
 -- higher-ranked body. A top source that states none or failed still blocks lower fallback (ct-30fp).
 SELECT * FROM appearance_ranked_sources
 WHERE effective_state='present' AND (top_code%2=0 OR 2*priority-1=top_code)
), unnested_listed AS (
 SELECT
  s.record_sha_hex,
  s.source,
  s.occasion,
  s.context_key,
  s.event_id,
  s.package_id,
  s.page_url,
  s.resolved_base,
  s.priority,
  unnest(r.appearances) AS a,
  unnest(range(0,cast(array_length(r.appearances) AS BIGINT))) AS ordinal
 FROM selected_observations s
 JOIN selected_appearance_records r ON r.record_sha_hex=s.record_sha_hex AND r.source=s.source
 WHERE r.appearances IS NOT NULL AND coalesce(array_length(r.appearances),0)>0
), listed_occurrences AS (
 SELECT
  record_sha_hex,
  source,
  occasion,
  context_key,
  event_id,
  package_id,
  page_url,
  resolved_base,
  priority,
  ordinal,
  coalesce(nullif(trim(a['source_locator']),''),source||':witness['||cast(ordinal+1 AS VARCHAR)||']') AS source_locator,
  nullif(trim(a['name_key']),'') AS name_key,
  nullif(trim(a['name']),'') AS name,
  nullif(trim(a['rank']),'') AS rank,
  nullif(trim(a['credentials']),'') AS credentials,
  nullif(trim(a['honorific']),'') AS honorific,
  nullif(trim(a['given']),'') AS given,
  nullif(trim(a['middle']),'') AS middle,
  nullif(trim(a['family']),'') AS family,
  nullif(trim(a['suffix']),'') AS suffix,
  nullif(trim(a['position']),'') AS position,
  nullif(trim(a['organization']),'') AS organization,
  nullif(trim(a['on_behalf_of']),'') AS on_behalf_of,
  nullif(trim(a['location']),'') AS location,
  nullif(trim(a['panel']),'') AS panel,
  cast(a['panel_order'] AS SMALLINT) AS panel_order,
  cast(a['display_order'] AS SMALLINT) AS display_order,
  nullif(trim(a['witness_type']),'') AS witness_type,
  a['testified'] AS testified,
  nullif(trim(a['bioguide_id']),'') AS bioguide_id,
  a['document_links'] AS document_links,
  'listed' AS listing_status,
  cast(NULL AS DATE) AS last_listed_on,
  cast(NULL AS DATE) AS unlisted_since,
  cast(NULL AS VARCHAR) AS unlisted_by_record_sha
 FROM unnested_listed
), all_occurrences AS (
 SELECT * FROM listed_occurrences
 UNION ALL
 SELECT * FROM congress_gov_retained_witnesses
), normalized AS (
 SELECT *,
  coalesce(package_id,'') AS package_key,
  coalesce(trim(regexp_replace(lower(name),'[^\p{L}\p{N}]+',' ','g')),'') AS name_t,
  coalesce(trim(regexp_replace(lower(organization),'[^\p{L}\p{N}]+',' ','g')),'') AS organization_t,
  coalesce(trim(regexp_replace(lower(position),'[^\p{L}\p{N}]+',' ','g')),'') AS position_t,
  substr(encode(sha256(json_array(occasion,source,record_sha_hex,cast(ordinal AS VARCHAR),context_key,listing_status)),'hex'),1,16) AS occ_id
 FROM all_occurrences
), ranked AS (
 SELECT *,
  row_number() OVER(
   PARTITION BY occasion,source,package_key,name_t,organization_t,position_t
   ORDER BY (listing_status='listed') DESC,panel_order ASC NULLS LAST,display_order ASC NULLS LAST,source_locator ASC,record_sha_hex ASC
  ) AS occurrence_ordinal
 FROM normalized
)
SELECT *,
 substr(encode(sha256(json_array('witness-appearance-v3',occasion,source,package_key,name_t,organization_t,position_t,occurrence_ordinal)),'hex'),1,16) AS v3_key
FROM ranked
