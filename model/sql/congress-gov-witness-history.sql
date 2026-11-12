-- Multi-read Congress.gov witness bodies ordered from newest (cg_rn=1) to oldest (ct-960v).
WITH active_cg_occasions AS (
 SELECT occasion,record_sha_hex AS cur_sha
 FROM appearance_ranked_sources
 WHERE source='congress_gov' AND effective_state IN ('present','empty','absent')
  AND (top_code%2=0 OR 2*priority-1=top_code)
), cg_bodies AS (
 SELECT
  o.occasion,
  o.record_sha_hex,
  ac.cur_sha,
  max(o.updated) AS updated,
  min(coalesce(o.first_retrieved_at,o.retrieved_at)) AS first_retrieved_at,
  max(o.retrieved_at) AS retrieved_at,
  min(o.context_key) AS context_key,
  min(o.event_id) AS event_id,
  min(o.package_id) AS package_id,
  min(o.page_url) AS page_url,
  min(o.resolved_base) AS resolved_base,
  min(o.priority) AS priority,
  min(o.effective_state) AS effective_state
 FROM appearance_observations o
 JOIN active_cg_occasions ac ON o.occasion=ac.occasion
 WHERE o.source='congress_gov' AND o.observation_eligible
  AND (o.effective_state IN ('present','empty') OR (o.effective_state='absent' AND o.updated IS NOT NULL))
 GROUP BY o.occasion,o.record_sha_hex,ac.cur_sha
), cg_history_all AS (
 SELECT *,
  coalesce(
   cast(arrow_cast(retrieved_at,'Timestamp(Microsecond, None)') AS DATE),
   cast(arrow_cast(updated,'Timestamp(Microsecond, None)') AS DATE)
  ) AS obs_date,
  coalesce(
   cast(arrow_cast(coalesce(first_retrieved_at,retrieved_at),'Timestamp(Microsecond, None)') AS DATE),
   cast(arrow_cast(updated,'Timestamp(Microsecond, None)') AS DATE)
  ) AS first_obs_date,
  row_number() OVER(
   PARTITION BY occasion
   ORDER BY (record_sha_hex=cur_sha) DESC,updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,(effective_state='present') DESC,record_sha_hex ASC
  ) AS cg_rn
 FROM cg_bodies
), prior_present_occasions AS (
 SELECT DISTINCT occasion
 FROM cg_history_all
 WHERE cg_rn>1 AND effective_state='present'
)
SELECT
 h.occasion,
 h.record_sha_hex,
 h.cur_sha,
 h.updated,
 h.retrieved_at,
 h.context_key,
 h.event_id,
 h.package_id,
 h.page_url,
 h.resolved_base,
 h.priority,
 h.effective_state,
 h.obs_date,
 h.first_obs_date,
 h.cg_rn
FROM prior_present_occasions p
JOIN cg_history_all h ON p.occasion=h.occasion
