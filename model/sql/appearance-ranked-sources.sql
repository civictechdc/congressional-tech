-- Ranked witness observations per occasion and publisher source (ct-960v, ct-46f3).
-- Materialized over narrow appearance_observations rows (before unnesting appearance arrays) so both
-- congress_gov_witness_history and appearance_occurrences share one source-ranking pass.
WITH prior_cg_present AS (
 SELECT DISTINCT occasion
 FROM appearance_observations
 WHERE source='congress_gov' AND observation_eligible AND effective_state='present'
), eligible_observations AS (
 SELECT ao.*,
  pcp.occasion IS NOT NULL AS has_prior_cg_present
 FROM prior_cg_present pcp
 RIGHT JOIN (SELECT * FROM appearance_observations WHERE observation_eligible) ao
  ON ao.source='congress_gov' AND ao.occasion=pcp.occasion
), ranked_context_observations AS (
 SELECT *,
  row_number() OVER(
   PARTITION BY occasion,source,context_key,coalesce(package_id,'')
   ORDER BY
    CASE
     WHEN has_prior_cg_present THEN (effective_state IN ('present','empty') OR (effective_state='absent' AND updated IS NOT NULL))
     ELSE (effective_state IN ('present','empty'))
    END DESC,
    CASE WHEN NOT has_prior_cg_present THEN (effective_state='absent') END ASC NULLS FIRST,
    updated DESC NULLS LAST,
    (effective_state IN ('present','empty')) DESC,
    (effective_state='absent') ASC,
    retrieved_at DESC NULLS LAST,
    (effective_state='present') DESC,
    record_sha_hex ASC
  ) AS ctx_rn
 FROM eligible_observations
), current_context_observations AS (
 SELECT *
 FROM ranked_context_observations
 WHERE ctx_rn=1
), superseded_source_bodies AS (
 SELECT DISTINCT old.occasion,old.source,old.record_sha_hex
 FROM ranked_context_observations old
 JOIN current_context_observations cur
  ON old.occasion=cur.occasion AND old.source=cur.source AND old.context_key=cur.context_key
  AND coalesce(old.package_id,'')=coalesce(cur.package_id,'')
 WHERE old.ctx_rn>1 AND old.record_sha_hex<>cur.record_sha_hex
), ranked_source_observations AS (
 SELECT c.*,
  -- One current body per print: several prints that stand for one meeting each keep their witnesses.
  row_number() OVER(
   PARTITION BY c.occasion,c.source,coalesce(c.package_id,'')
   ORDER BY
    CASE
     WHEN c.has_prior_cg_present THEN (c.effective_state IN ('present','empty') OR (c.effective_state='absent' AND c.updated IS NOT NULL))
     ELSE (c.effective_state IN ('present','empty'))
    END DESC,
    CASE WHEN NOT c.has_prior_cg_present THEN (c.effective_state='absent') END ASC NULLS FIRST,
    (sb.record_sha_hex IS NOT NULL) ASC,
    c.updated DESC NULLS LAST,
    (c.effective_state IN ('present','empty')) DESC,
    (c.effective_state='absent') ASC,
    c.retrieved_at DESC NULLS LAST,
    (c.effective_state='present') DESC,
    c.record_sha_hex ASC,
    c.context_key ASC
  ) AS obs_rn
 FROM superseded_source_bodies sb
 RIGHT JOIN current_context_observations c
  ON c.occasion=sb.occasion AND c.source=sb.source AND c.record_sha_hex=sb.record_sha_hex
), current_source_observations AS (
 SELECT *
 FROM ranked_source_observations
 WHERE obs_rn=1
)
-- When Congress.gov previously listed witnesses on an occasion and later wiped its list (either empty array or
-- omitted witnesses key under a later updateDate), its retained no_longer_listed witnesses still stand alongside
-- lower-priority prints or Senate pages (ct-960v).
SELECT c.* EXCLUDE(has_prior_cg_present),first_value(
 CASE
  WHEN c.effective_state='present' OR (c.source='congress_gov' AND c.effective_state IN ('empty','absent') AND c.has_prior_cg_present)
   THEN 2*c.priority
  ELSE 2*c.priority-1
 END
) OVER(
 PARTITION BY c.occasion
 ORDER BY CASE
  WHEN c.effective_state='present' OR (c.source='congress_gov' AND c.effective_state IN ('empty','absent') AND c.has_prior_cg_present)
   THEN 2*c.priority
  ELSE 2*c.priority-1
 END ASC
) AS top_code
FROM current_source_observations c
WHERE c.effective_state IN ('present','empty','unresolved')
 OR (c.source='congress_gov' AND c.effective_state='absent' AND c.updated IS NOT NULL AND c.has_prior_cg_present)
