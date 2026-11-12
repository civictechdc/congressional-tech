-- Retired person_key ledger (person_aliases) with 1-hop carry over person_aliases_fresh (ct-ha10).
WITH live_people AS (
 SELECT person_key FROM entity_people
), base_filtered AS (
 SELECT ba.*
 FROM person_aliases_fresh fa
 RIGHT ANTI JOIN (
  live_people lp
  RIGHT ANTI JOIN base_person_aliases ba ON lp.person_key=ba.old_person_key
 ) ON fa.old_person_key=ba.old_person_key
 WHERE ba.old_person_key IS NOT NULL
), ba_unamb_direct AS (
 SELECT
  ba.old_person_key,
  ba.person_key,
  'unambiguous' AS status,
  ba.kind,
  ba.decision_id,
  ba.last_release_id,
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS candidate_keys
 FROM base_filtered ba
 JOIN live_people lp ON lp.person_key=ba.person_key
 WHERE ba.status='unambiguous'
), ba_unamb_hopped AS (
 SELECT
  ba.old_person_key,
  fa.person_key,
  fa.status,
  CASE WHEN fa.status='unresolved' THEN NULL ELSE coalesce(fa.kind,ba.kind) END AS kind,
  coalesce(fa.decision_id,ba.decision_id) AS decision_id,
  ba.last_release_id,
  fa.candidate_keys
 FROM (
  SELECT bf.*
  FROM live_people lp
  RIGHT ANTI JOIN (SELECT * FROM base_filtered WHERE status='unambiguous') bf ON lp.person_key=bf.person_key
 ) ba
 JOIN person_aliases_fresh fa ON fa.old_person_key=ba.person_key
), ba_amb_unnested AS (
 SELECT old_person_key,unnest(candidate_keys) AS ck
 FROM base_filtered
 WHERE status='ambiguous' AND candidate_keys IS NOT NULL
), fa_amb_unnested AS (
 SELECT old_person_key,unnest(candidate_keys) AS live_ck
 FROM person_aliases_fresh
 WHERE status='ambiguous' AND candidate_keys IS NOT NULL
), ba_amb_live AS (
 SELECT DISTINCT old_person_key,live_ck FROM (
  SELECT u.old_person_key,u.ck AS live_ck
  FROM ba_amb_unnested u JOIN live_people lp ON lp.person_key=u.ck
  UNION ALL
  SELECT u.old_person_key,fa.person_key AS live_ck
  FROM ba_amb_unnested u JOIN person_aliases_fresh fa ON fa.old_person_key=u.ck
  WHERE fa.status='unambiguous' AND fa.person_key IS NOT NULL
  UNION ALL
  SELECT u.old_person_key,fa.live_ck
  FROM ba_amb_unnested u JOIN fa_amb_unnested fa ON fa.old_person_key=u.ck
 ) WHERE live_ck IS NOT NULL
), ba_amb_agg AS (
 SELECT
  old_person_key,
  min(live_ck) AS min_ck,
  max(live_ck) AS max_ck,
  array_agg(live_ck ORDER BY live_ck) AS live_candidates
 FROM ba_amb_live
 GROUP BY old_person_key
), ba_amb_resolved AS (
 SELECT
  ba.old_person_key,
  CASE WHEN a.min_ck IS NOT NULL AND a.min_ck=a.max_ck THEN a.min_ck END AS person_key,
  CASE
   WHEN a.min_ck IS NOT NULL AND a.min_ck<>a.max_ck THEN 'ambiguous'
   WHEN a.min_ck IS NOT NULL AND a.min_ck=a.max_ck THEN 'unambiguous'
   ELSE 'unresolved'
  END AS status,
  CASE
   WHEN a.min_ck IS NOT NULL AND a.min_ck<>a.max_ck THEN ba.kind
   WHEN a.min_ck IS NOT NULL AND a.min_ck=a.max_ck THEN 'merged'
  END AS kind,
  ba.decision_id,
  ba.last_release_id,
  CASE
   WHEN a.min_ck IS NOT NULL AND a.min_ck<>a.max_ck THEN a.live_candidates
   ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
  END AS candidate_keys
 FROM ba_amb_agg a
 RIGHT JOIN (SELECT * FROM base_filtered WHERE status='ambiguous') ba ON a.old_person_key=ba.old_person_key
), ba_unresolved AS (
 SELECT
  old_person_key,
  cast(NULL AS VARCHAR) AS person_key,
  'unresolved' AS status,
  cast(NULL AS VARCHAR) AS kind,
  decision_id,
  last_release_id,
  arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') AS candidate_keys
 FROM base_filtered
 WHERE status='unresolved'
)
SELECT * FROM person_aliases_fresh
UNION ALL
SELECT * FROM ba_unamb_direct
UNION ALL
SELECT * FROM ba_unamb_hopped
UNION ALL
SELECT * FROM ba_amb_resolved
UNION ALL
SELECT * FROM ba_unresolved
