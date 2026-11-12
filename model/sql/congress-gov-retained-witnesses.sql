-- Retained Congress.gov witnesses marked no_longer_listed (ct-960v).
WITH cg_cur_items AS (
 SELECT * FROM congress_gov_witness_items WHERE cg_rn=1
), cg_hist_items AS (
 SELECT * FROM congress_gov_witness_items WHERE cg_rn>1
), cg_family_pairs AS (
 SELECT
  h.occasion,
  h.cg_rn,
  h.ordinal,
  hp.given AS h_given,
  cp.given AS c_given
 FROM cg_hist_items h
 JOIN congress_gov_witness_items c ON c.occasion=h.occasion AND c.cg_rn<h.cg_rn AND c.source_locator=h.source_locator
 JOIN appearance_people hp ON hp.record_sha_hex=h.record_sha_hex AND hp.source='congress_gov' AND hp.ordinal=h.ordinal
 JOIN appearance_people cp ON cp.record_sha_hex=c.record_sha_hex AND cp.source='congress_gov' AND cp.ordinal=c.ordinal
 JOIN person_same_family sf ON sf.left_family=hp.family AND sf.right_family=cp.family
 WHERE coalesce(h.position,h.organization,h.bioguide_id) IS NOT NULL
  AND h.position_t=c.position_t AND h.organization_t=c.organization_t
  AND (h.on_behalf_of IS NOT DISTINCT FROM c.on_behalf_of)
  AND (h.location IS NOT DISTINCT FROM c.location)
  AND (h.panel IS NOT DISTINCT FROM c.panel)
  AND coalesce(h.bioguide_id,'')=coalesce(c.bioguide_id,'')
  AND hp.family IS NOT NULL AND cp.family IS NOT NULL
), cg_locator_matched AS (
 SELECT DISTINCT occasion,cg_rn,ordinal FROM (
  SELECT occasion,cg_rn,ordinal
  FROM cg_family_pairs
  WHERE h_given IS NULL OR c_given IS NULL
  UNION ALL
  SELECT fp.occasion,fp.cg_rn,fp.ordinal
  FROM cg_family_pairs fp
  JOIN person_given_matches gm ON gm.left_given=fp.h_given AND gm.right_given=fp.c_given
  WHERE fp.h_given IS NOT NULL AND fp.c_given IS NOT NULL
 )
), cg_dropped_candidates AS (
 SELECT h.*
 FROM cg_cur_items cc
 RIGHT ANTI JOIN (
  SELECT h0.*
  FROM cg_locator_matched lm
  RIGHT ANTI JOIN cg_hist_items h0
   ON lm.occasion=h0.occasion AND lm.cg_rn=h0.cg_rn AND lm.ordinal=h0.ordinal
 ) h
  ON cc.occasion=h.occasion AND cc.name_t=h.name_t AND cc.organization_t=h.organization_t
  AND cc.position_t=h.position_t AND cc.dup_ord=h.dup_ord
), cg_dropped_picked AS (
 SELECT *,
  row_number() OVER(
   PARTITION BY occasion,name_t,organization_t,position_t,dup_ord
   ORDER BY cg_rn ASC,ordinal ASC
  ) AS pick_rn
 FROM cg_dropped_candidates
), cg_picked_top AS (
 SELECT * FROM cg_dropped_picked WHERE pick_rn=1
), cg_dropped_unlisted AS (
 SELECT
  p.occasion,p.name_t,p.organization_t,p.position_t,p.dup_ord,
  max(u.cg_rn) AS unlisted_rn
 FROM cg_picked_top p
 JOIN congress_gov_witness_history u ON u.occasion=p.occasion AND u.cg_rn<p.cg_rn
 GROUP BY p.occasion,p.name_t,p.organization_t,p.position_t,p.dup_ord
)
SELECT
 p.record_sha_hex,
 p.source,
 p.occasion,
 p.context_key,
 p.event_id,
 p.package_id,
 p.page_url,
 p.resolved_base,
 p.priority,
 p.ordinal,
 p.source_locator,
 p.name_key,
 p.name,
 p.rank,
 p.credentials,
 p.honorific,
 p.given,
 p.middle,
 p.family,
 p.suffix,
 p.position,
 p.organization,
 p.on_behalf_of,
 p.location,
 p.panel,
 p.panel_order,
 p.display_order,
 p.witness_type,
 p.testified,
 p.bioguide_id,
 p.document_links,
 'no_longer_listed' AS listing_status,
 p.obs_date AS last_listed_on,
 uh.first_obs_date AS unlisted_since,
 uh.record_sha_hex AS unlisted_by_record_sha
FROM cg_picked_top p
JOIN cg_dropped_unlisted un
 ON un.occasion=p.occasion AND un.name_t=p.name_t AND un.organization_t=p.organization_t
 AND un.position_t=p.position_t AND un.dup_ord=p.dup_ord
JOIN congress_gov_witness_history uh ON uh.occasion=p.occasion AND uh.cg_rn=un.unlisted_rn
