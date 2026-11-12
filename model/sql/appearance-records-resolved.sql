-- Carry live witness_key forward from prior_witnesses by Tier 1 (source, record_sha, source_locator) and
-- Tier 2 (source, occasion, print, normalized name/organization/position, occurrence_ordinal); mint witness-appearance-v3
-- only for genuinely new or re-keyed entries (ct-46f3, ct-960v).
WITH prior_norm AS (
 SELECT
  witness_key,
  occasion,
  source,
  coalesce(package_id,'') AS package_key,
  lower(encode(record_sha,'hex')) AS record_sha_hex,
  source_locator,
  panel_order,
  display_order,
  coalesce(listing_status,'listed') AS listing_status,
  coalesce(trim(regexp_replace(lower(name),'[^\p{L}\p{N}]+',' ','g')),'') AS name_t,
  coalesce(trim(regexp_replace(lower(organization),'[^\p{L}\p{N}]+',' ','g')),'') AS organization_t,
  coalesce(trim(regexp_replace(lower(position),'[^\p{L}\p{N}]+',' ','g')),'') AS position_t
 FROM prior_witnesses
 WHERE witness_key IS NOT NULL
), prior_t1 AS (
 SELECT source,record_sha_hex,source_locator,min(witness_key) AS witness_key
 FROM prior_norm
 WHERE record_sha_hex IS NOT NULL AND source_locator IS NOT NULL
 GROUP BY source,record_sha_hex,source_locator
 HAVING count(*)=1
), occ_t1 AS (
 SELECT source,record_sha_hex,source_locator,min(occ_id) AS occ_id
 FROM appearance_occurrences
 GROUP BY source,record_sha_hex,source_locator
 HAVING count(*)=1
), tier1_carry AS (
 SELECT o.occ_id,p.witness_key,'tier1' AS carry_tier
 FROM prior_t1 p
 JOIN occ_t1 o ON p.source=o.source AND p.record_sha_hex=o.record_sha_hex AND p.source_locator=o.source_locator
), rem_prior AS (
 SELECT p.*
 FROM tier1_carry t1
 RIGHT ANTI JOIN prior_norm p ON t1.witness_key=p.witness_key
), rem_occ AS (
 SELECT o.*
 FROM tier1_carry t1
 RIGHT ANTI JOIN appearance_occurrences o ON t1.occ_id=o.occ_id
), numbered_rem_prior AS (
 SELECT witness_key,source,occasion,package_key,name_t,organization_t,position_t,
  row_number() OVER(
   PARTITION BY source,occasion,package_key,name_t,organization_t,position_t
   ORDER BY (listing_status='listed') DESC,panel_order ASC NULLS LAST,display_order ASC NULLS LAST,source_locator ASC,witness_key ASC
  ) AS grp_rn
 FROM rem_prior
 WHERE name_t<>''
), rem_prior_counts AS (
 SELECT source,occasion,package_key,name_t,organization_t,position_t,max(grp_rn) AS p_grp_cnt
 FROM numbered_rem_prior
 GROUP BY source,occasion,package_key,name_t,organization_t,position_t
), numbered_rem_occ AS (
 SELECT occ_id,source,occasion,package_key,name_t,organization_t,position_t,
  row_number() OVER(
   PARTITION BY source,occasion,package_key,name_t,organization_t,position_t
   ORDER BY (listing_status='listed') DESC,panel_order ASC NULLS LAST,display_order ASC NULLS LAST,source_locator ASC,record_sha_hex ASC
  ) AS grp_rn
 FROM rem_occ
 WHERE name_t<>''
), rem_occ_counts AS (
 SELECT source,occasion,package_key,name_t,organization_t,position_t,max(grp_rn) AS o_grp_cnt
 FROM numbered_rem_occ
 GROUP BY source,occasion,package_key,name_t,organization_t,position_t
), matched_tier2_groups AS (
 SELECT pc.source,pc.occasion,pc.package_key,pc.name_t,pc.organization_t,pc.position_t
 FROM rem_prior_counts pc
 JOIN rem_occ_counts oc
  ON pc.source=oc.source AND pc.occasion=oc.occasion AND pc.package_key=oc.package_key
  AND pc.name_t=oc.name_t AND pc.organization_t=oc.organization_t AND pc.position_t=oc.position_t
  AND pc.p_grp_cnt=oc.o_grp_cnt
), tier2_carry AS (
 SELECT o.occ_id,p.witness_key,'tier2' AS carry_tier
 FROM (matched_tier2_groups g JOIN numbered_rem_prior p
  ON g.source=p.source AND g.occasion=p.occasion AND g.package_key=p.package_key
  AND g.name_t=p.name_t AND g.organization_t=p.organization_t AND g.position_t=p.position_t)
 JOIN numbered_rem_occ o
  ON p.source=o.source AND p.occasion=o.occasion AND p.package_key=o.package_key
  AND p.name_t=o.name_t AND p.organization_t=o.organization_t AND p.position_t=o.position_t
  AND p.grp_rn=o.grp_rn
), carried AS (
 SELECT * FROM tier1_carry
 UNION ALL
 SELECT * FROM tier2_carry
), reserved_keys AS (
 SELECT DISTINCT witness_key AS key FROM prior_witnesses WHERE witness_key IS NOT NULL
 UNION
 SELECT DISTINCT old_key AS key FROM base_witness_key_map WHERE old_key IS NOT NULL
 UNION
 SELECT DISTINCT old_key AS key FROM historical_witness_keys WHERE old_key IS NOT NULL
), with_witness_key AS (
 SELECT
  CASE
   WHEN c.witness_key IS NOT NULL THEN c.witness_key
   WHEN rk.key IS NULL THEN o.v3_key
   ELSE substr(encode(sha256(json_array('witness-appearance-v3-rekey',o.occasion,o.source,o.package_key,o.name_t,o.organization_t,o.position_t,o.occurrence_ordinal,o.record_sha_hex,o.source_locator)),'hex'),1,16)
  END AS witness_key,
  coalesce(c.carry_tier,'minted') AS carry_tier,
  o.*
 FROM reserved_keys rk
 RIGHT JOIN (carried c RIGHT JOIN appearance_occurrences o ON c.occ_id=o.occ_id)
  ON rk.key=o.v3_key
), raw_link_rows AS (
 SELECT
  witness_key,
  resolved_base,
  unnest(document_links) AS raw_link,
  unnest(range(0,cast(array_length(document_links) AS BIGINT))) AS link_idx
 FROM with_witness_key
 WHERE document_links IS NOT NULL AND coalesce(array_length(document_links),0)>0
), resolved_link_rows AS (
 SELECT
  witness_key,
  link_idx,
  CASE
   WHEN resolved_base IS NOT NULL THEN url_resolve(trim(raw_link),resolved_base)
   WHEN regexp_like(trim(raw_link),'(?i)^https?://') THEN trim(raw_link)
  END AS resolved_url
 FROM raw_link_rows
 WHERE raw_link IS NOT NULL AND trim(raw_link)<>''
), aggregated_links AS (
 SELECT
  witness_key,
  array_agg(resolved_url ORDER BY link_idx) AS document_urls
 FROM resolved_link_rows
 WHERE resolved_url IS NOT NULL AND regexp_like(resolved_url,'(?i)^https?://')
 GROUP BY witness_key
)
SELECT
 w.witness_key,
 w.occasion,
 w.source,
 arrow_cast(decode(w.record_sha_hex,'hex'),'FixedSizeBinary(32)') AS record_sha,
 w.record_sha_hex,
 w.source_locator,
 w.context_key,
 w.event_id,
 w.package_id,
 w.package_key,
 w.page_url,
 w.name_key,
 w.name,
 w.rank,
 w.credentials,
 w.honorific,
 w.given,
 w.middle,
 w.family,
 w.suffix,
 w.position,
 w.organization,
 w.on_behalf_of,
 w.location,
 w.panel,
 w.panel_order,
 w.display_order,
 w.witness_type,
 w.testified,
 w.bioguide_id,
 coalesce(al.document_urls,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS document_urls,
 w.ordinal,
 w.occurrence_ordinal,
 w.name_t,
 w.organization_t,
 w.position_t,
 w.carry_tier,
 w.listing_status,
 w.last_listed_on,
 w.unlisted_since,
 w.unlisted_by_record_sha
FROM aggregated_links al
RIGHT JOIN with_witness_key w ON w.witness_key=al.witness_key
