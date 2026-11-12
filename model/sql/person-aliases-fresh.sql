-- Fresh retired person_key aliases from prior_people keys that left entity_people (ct-ha10).
-- Materialized once so person_aliases' 1-hop carry does not re-scan prior_people or appearance_records_resolved.
WITH live_people AS (
 SELECT person_key FROM entity_people
), gone_people AS (
 SELECT pp.person_key AS old_person_key,pp.release_id AS last_release_id,pp.witness_keys
 FROM live_people lp
 RIGHT ANTI JOIN prior_people pp ON lp.person_key=pp.person_key
 WHERE pp.person_key IS NOT NULL
), gone_wks AS (
 SELECT old_person_key,unnest(witness_keys) AS prior_wk
 FROM gone_people
 WHERE witness_keys IS NOT NULL
), wkm_amb_unnested AS (
 SELECT old_key,unnest(candidate_keys) AS cand_wk
 FROM witness_key_map
 WHERE status='ambiguous' AND candidate_keys IS NOT NULL
), resolved_wks AS (
 SELECT g.old_person_key,r.witness_key AS cur_wk,true AS accounted
 FROM gone_wks g
 JOIN appearance_records_resolved r ON r.witness_key=g.prior_wk
 UNION ALL
 SELECT g.old_person_key,m.witness_key AS cur_wk,true AS accounted
 FROM gone_wks g
 JOIN witness_key_map m ON m.old_key=g.prior_wk
 WHERE m.status='unambiguous' AND m.witness_key IS NOT NULL
 UNION ALL
 SELECT g.old_person_key,ma.cand_wk AS cur_wk,true AS accounted
 FROM gone_wks g
 JOIN wkm_amb_unnested ma ON ma.old_key=g.prior_wk
 UNION ALL
 SELECT g.old_person_key,cast(NULL AS VARCHAR) AS cur_wk,true AS accounted
 FROM gone_wks g
 JOIN witness_key_map m ON m.old_key=g.prior_wk
 WHERE m.status='unresolved'
), mapped_pks AS (
 SELECT
  rw.old_person_key,
  wp.person_key AS cand_pk,
  wp.decision_id,
  wp.decision_kind,
  rw.accounted
 FROM witness_people wp
 RIGHT JOIN resolved_wks rw ON wp.witness_key=rw.cur_wk
), distinct_cand_pks AS (
 SELECT DISTINCT old_person_key,cand_pk
 FROM mapped_pks
 WHERE cand_pk IS NOT NULL
), cand_arrays AS (
 SELECT old_person_key,array_agg(cand_pk ORDER BY cand_pk) AS candidate_keys
 FROM distinct_cand_pks
 GROUP BY old_person_key
), target_fan_in AS (
 SELECT cand_pk,min(src_pk)<>max(src_pk) AS has_multiple_sources FROM (
  SELECT d.cand_pk,d.old_person_key AS src_pk FROM distinct_cand_pks d
  UNION ALL
  SELECT lp.person_key AS cand_pk,lp.person_key AS src_pk
  FROM live_people lp JOIN prior_people pp ON pp.person_key=lp.person_key
 ) GROUP BY cand_pk
), fresh_grouped AS (
 SELECT
  m.old_person_key,
  min(m.cand_pk) AS min_pk,
  max(m.cand_pk) AS max_pk,
  min(m.decision_id) AS decision_id,
  min(m.decision_kind) AS decision_kind,
  bool_or(m.accounted) AS any_accounted
 FROM mapped_pks m
 GROUP BY m.old_person_key
)
SELECT
 gp.old_person_key,
 CASE WHEN fg.min_pk IS NOT NULL AND fg.min_pk=fg.max_pk THEN fg.min_pk END AS person_key,
 CASE
  WHEN fg.min_pk IS NOT NULL AND fg.min_pk=fg.max_pk THEN 'unambiguous'
  WHEN fg.min_pk IS NOT NULL AND fg.min_pk<>fg.max_pk THEN 'ambiguous'
  ELSE 'unresolved'
 END AS status,
 CASE
  WHEN fg.decision_kind='merge' THEN 'merged'
  WHEN fg.decision_kind='split' THEN 'split'
  WHEN fg.decision_kind='hide' THEN 'hidden'
  WHEN fg.min_pk IS NOT NULL AND fg.min_pk=fg.max_pk THEN
   CASE WHEN coalesce(fi.has_multiple_sources,false) THEN 'merged' ELSE 'regrouped' END
  WHEN fg.min_pk IS NOT NULL AND fg.min_pk<>fg.max_pk THEN 'split'
 END AS kind,
 fg.decision_id,
 gp.last_release_id,
 CASE
  WHEN fg.min_pk IS NOT NULL AND fg.min_pk<>fg.max_pk THEN ca.candidate_keys
  ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
 END AS candidate_keys
FROM target_fan_in fi
RIGHT JOIN (
 cand_arrays ca
 RIGHT JOIN (
  fresh_grouped fg
  JOIN gone_people gp ON gp.old_person_key=fg.old_person_key
 ) ON ca.old_person_key=fg.old_person_key
) ON fi.cand_pk=fg.min_pk
WHERE fg.any_accounted
