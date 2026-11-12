-- Unnested Congress.gov witness entries across multi-read occasions (ct-960v).
WITH cg_unnested AS (
 SELECT
  h.occasion,
  h.cg_rn,
  h.obs_date,
  h.record_sha_hex,
  h.context_key,
  h.event_id,
  h.package_id,
  h.page_url,
  h.resolved_base,
  h.priority,
  unnest(r.appearances) AS a,
  unnest(range(0,cast(array_length(r.appearances) AS BIGINT))) AS ordinal
 FROM congress_gov_witness_history h
 JOIN selected_appearance_records r ON r.record_sha_hex=h.record_sha_hex AND r.source='congress_gov'
 WHERE h.effective_state='present' AND r.appearances IS NOT NULL AND coalesce(array_length(r.appearances),0)>0
), cg_extracted_raw AS (
 SELECT
  occasion,
  cg_rn,
  obs_date,
  record_sha_hex,
  'congress_gov' AS source,
  context_key,
  event_id,
  package_id,
  page_url,
  resolved_base,
  priority,
  ordinal,
  coalesce(nullif(trim(a['source_locator']),''),'congress_gov:witness['||cast(ordinal+1 AS VARCHAR)||']') AS source_locator,
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
  coalesce(trim(regexp_replace(lower(a['name']),'[^\p{L}\p{N}]+',' ','g')),'') AS name_t,
  coalesce(trim(regexp_replace(lower(a['organization']),'[^\p{L}\p{N}]+',' ','g')),'') AS organization_t,
  coalesce(trim(regexp_replace(lower(a['position']),'[^\p{L}\p{N}]+',' ','g')),'') AS position_t
 FROM cg_unnested
)
SELECT *,
 row_number() OVER(
  PARTITION BY occasion,cg_rn,name_t,organization_t,position_t
  ORDER BY panel_order ASC NULLS LAST,display_order ASC NULLS LAST,source_locator ASC
 ) AS dup_ord
FROM cg_extracted_raw
