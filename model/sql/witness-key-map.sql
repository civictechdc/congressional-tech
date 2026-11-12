-- Redirect retired live witness keys and carry base_witness_key_map forward one hop (ct-46f3).
-- Reads materialized witness_key_map_fresh, base_witness_key_map, and historical_witness_keys.
WITH published_keys AS (
 SELECT DISTINCT witness_key FROM appearance_records_resolved
), bm_filtered AS (
 SELECT bm.*
 FROM witness_key_map_fresh nm
 RIGHT ANTI JOIN (
  published_keys pk
  RIGHT ANTI JOIN base_witness_key_map bm ON pk.witness_key=bm.old_key
 ) ON nm.old_key=bm.old_key
 WHERE bm.old_key IS NOT NULL
), bm_unamb_direct AS (
 SELECT
  bm.old_key,
  bm.witness_key,
  'unambiguous' AS status,
  bm.basis,
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS candidate_keys,
  bm.occasion,
  bm.source
 FROM bm_filtered bm
 JOIN published_keys pk ON pk.witness_key=bm.witness_key
 WHERE bm.status='unambiguous'
), bm_unamb_hopped AS (
 SELECT
  bm.old_key,
  CASE WHEN nm.status='unambiguous' THEN nm.witness_key END AS witness_key,
  nm.status,
  CASE WHEN nm.status<>'unresolved' THEN bm.basis END AS basis,
  CASE
   WHEN nm.status='ambiguous' THEN nm.candidate_keys
   ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
  END AS candidate_keys,
  bm.occasion,
  bm.source
 FROM (
  published_keys pk
  RIGHT ANTI JOIN (SELECT * FROM bm_filtered WHERE status='unambiguous') bm ON pk.witness_key=bm.witness_key
 )
 JOIN witness_key_map_fresh nm ON nm.old_key=bm.witness_key
), bm_amb_unnested AS (
 SELECT old_key,unnest(candidate_keys) AS ck
 FROM bm_filtered
 WHERE status='ambiguous' AND candidate_keys IS NOT NULL
), nm_amb_unnested AS (
 SELECT old_key,unnest(candidate_keys) AS live_ck
 FROM witness_key_map_fresh
 WHERE status='ambiguous' AND candidate_keys IS NOT NULL
), bm_amb_live AS (
 SELECT DISTINCT old_key,live_ck FROM (
  SELECT u.old_key,u.ck AS live_ck
  FROM bm_amb_unnested u JOIN published_keys pk ON pk.witness_key=u.ck
  UNION ALL
  SELECT u.old_key,nm.witness_key AS live_ck
  FROM bm_amb_unnested u JOIN witness_key_map_fresh nm ON nm.old_key=u.ck
  WHERE nm.status='unambiguous' AND nm.witness_key IS NOT NULL
  UNION ALL
  SELECT u.old_key,nm.live_ck
  FROM bm_amb_unnested u JOIN nm_amb_unnested nm ON nm.old_key=u.ck
 ) WHERE live_ck IS NOT NULL
), bm_amb_agg AS (
 SELECT old_key,count(live_ck) AS live_cnt,array_agg(live_ck ORDER BY live_ck) AS live_candidates
 FROM bm_amb_live
 GROUP BY old_key
), bm_amb_resolved AS (
 SELECT
  bm.old_key,
  cast(NULL AS VARCHAR) AS witness_key,
  CASE WHEN coalesce(a.live_cnt,0)>1 THEN 'ambiguous' ELSE 'unresolved' END AS status,
  CASE WHEN coalesce(a.live_cnt,0)>1 THEN bm.basis END AS basis,
  CASE
   WHEN coalesce(a.live_cnt,0)>1 THEN a.live_candidates
   ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
  END AS candidate_keys,
  bm.occasion,
  bm.source
 FROM bm_amb_agg a
 RIGHT JOIN (SELECT * FROM bm_filtered WHERE status='ambiguous') bm ON a.old_key=bm.old_key
), bm_unresolved AS (
 SELECT
  old_key,
  cast(NULL AS VARCHAR) AS witness_key,
  'unresolved' AS status,
  cast(NULL AS VARCHAR) AS basis,
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS candidate_keys,
  occasion,
  source
 FROM bm_filtered
 WHERE status='unresolved'
), carried_map_rows AS (
 SELECT * FROM bm_unamb_direct
 UNION ALL
 SELECT * FROM bm_unamb_hopped
 UNION ALL
 SELECT * FROM bm_amb_resolved
 UNION ALL
 SELECT * FROM bm_unresolved
), active_map_keys AS (
 SELECT old_key FROM witness_key_map_fresh
 UNION ALL
 SELECT old_key FROM carried_map_rows
), hk_filtered AS (
 SELECT hk.*
 FROM active_map_keys am
 RIGHT ANTI JOIN (
  published_keys pk
  RIGHT ANTI JOIN historical_witness_keys hk ON pk.witness_key=hk.old_key
 ) ON am.old_key=hk.old_key
), hk_unamb_candidates AS (
 SELECT
  hk.old_key,
  hk.occasion,
  hk.source,
  hk.basis,
  min(c.witness_key) AS witness_key,
  count(c.witness_key) AS cnt
 FROM hk_filtered hk
 JOIN appearance_records_resolved c
  ON c.source=hk.source AND c.record_sha_hex=hk.record_sha AND c.source_locator=hk.source_locator
 WHERE hk.status='unambiguous'
 GROUP BY hk.old_key,hk.occasion,hk.source,hk.basis
), hk_rows AS (
 SELECT
  old_key,
  witness_key,
  'unambiguous' AS status,
  basis,
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS candidate_keys,
  occasion,
  source
 FROM hk_unamb_candidates
 WHERE cnt=1
 UNION ALL
 SELECT
  hk.old_key,
  cast(NULL AS VARCHAR) AS witness_key,
  'unresolved' AS status,
  cast(NULL AS VARCHAR) AS basis,
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS candidate_keys,
  hk.occasion,
  hk.source
 FROM hk_filtered hk
 JOIN (SELECT DISTINCT record_sha_hex,source FROM selected_appearance_records) sr
  ON sr.record_sha_hex=hk.record_sha AND sr.source=hk.source
 WHERE hk.status='unresolved'
)
SELECT * FROM witness_key_map_fresh
UNION ALL
SELECT * FROM carried_map_rows
UNION ALL
SELECT * FROM hk_rows
