-- The current witness for each key in witness_key_priors (ct-kb4w), from the strongest evidence found;
-- a name alone never maps (ct-30fp).
--  occurrence: the same body and locator, published under another occasion or context key.
--  content: at the same occasion, source and print, a row equal in name and every other stated attribute,
--   with a non-name attribute stated or the same locator. Repeats of one person pair in list order.
--  locator: at the same locator of the same occasion, source and print, an edited name of the same
--   person (family and given name as witness_precedence judges them) with every other attribute equal
--   and position, organization or Bioguide ID stated.
-- One paired candidate maps. Several candidates without a unique pair are ambiguous.
-- A lone content candidate with a different repeat rank leaves the earlier occurrence unresolved.
WITH pairs AS (
 SELECT k.old_key,c.witness_key,1 AS tier,true AS paired
 FROM witness_key_priors k
 JOIN witness_key_current c ON c.source=k.source AND c.record_sha_hex=k.record_sha_hex AND c.source_locator=k.source_locator
 UNION ALL
 SELECT k.old_key,c.witness_key,2 AS tier,k.repeat_rank=c.repeat_rank AS paired
 FROM witness_key_priors k
 JOIN witness_key_current c ON c.occasion=k.occasion AND c.source=k.source AND c.package_key=k.package_key AND c.signature=k.signature
 WHERE k.name_key IS NOT NULL
  AND (coalesce(k.position,k.organization,k.on_behalf_of,k.bioguide_id) IS NOT NULL OR c.source_locator=k.source_locator)
 UNION ALL
 SELECT k.old_key,c.witness_key,3 AS tier,true AS paired
 FROM witness_key_priors k
 JOIN witness_key_current c ON c.occasion=k.occasion AND c.source=k.source AND c.package_key=k.package_key AND c.source_locator=k.source_locator
 WHERE (k.name_key IS DISTINCT FROM c.name_key)
  AND coalesce(k.position,k.organization,k.bioguide_id) IS NOT NULL
  AND (k.position IS NOT DISTINCT FROM c.position) AND (k.organization IS NOT DISTINCT FROM c.organization)
  AND (k.on_behalf_of IS NOT DISTINCT FROM c.on_behalf_of) AND (k.location IS NOT DISTINCT FROM c.location)
  AND (k.panel IS NOT DISTINCT FROM c.panel) AND (k.witness_type IS NOT DISTINCT FROM c.witness_type)
  AND (k.bioguide_id IS NOT DISTINCT FROM c.bioguide_id)
  AND (k.family=c.family OR (length(k.family)>=5 AND levenshtein(k.family,c.family)<=1))
  AND (k.given IS NULL OR c.given IS NULL OR k.given_canon=c.given_canon
   OR (length(k.given)>=3 AND length(c.given)>=3 AND substr(k.given,1,3)=substr(c.given,1,3))
   OR (length(k.given)=1 AND k.given=substr(c.given,1,1)) OR (length(c.given)=1 AND c.given=substr(k.given,1,1)))
), per_candidate AS (
 SELECT old_key,witness_key,min(tier) AS tier,bool_or(paired) AS paired
 FROM pairs
 GROUP BY old_key,witness_key
), best AS (
 SELECT *,min(tier) OVER (PARTITION BY old_key) AS best_tier FROM per_candidate
), decided AS (
 -- per_candidate holds one row per (old_key, witness_key), so plain counts need no count(DISTINCT).
 SELECT old_key,min(tier) AS tier,count(witness_key) AS candidates,count(witness_key) FILTER (WHERE paired) AS paired_candidates,
  min(witness_key) FILTER (WHERE paired) AS paired_key,
  array_agg(witness_key ORDER BY witness_key) AS candidate_keys
 FROM best
 WHERE tier=best_tier
 GROUP BY old_key
), olds AS (
 -- A key can come from several contexts of one body; its rows agree on all but the filing occasion.
 SELECT old_key,min(occasion) AS occasion,min(source) AS source
 FROM witness_key_priors
 GROUP BY old_key
)
SELECT
 o.old_key,
 o.occasion,
 o.source,
 CASE WHEN d.paired_candidates=1 THEN d.paired_key END AS witness_key,
 CASE
  WHEN d.paired_candidates=1 THEN 'unambiguous'
  WHEN d.candidates>1 THEN 'ambiguous'
  ELSE 'unresolved'
 END AS status,
 CASE WHEN d.paired_candidates=1 OR d.candidates>1 THEN
  CASE d.tier WHEN 1 THEN 'occurrence' WHEN 2 THEN 'content' WHEN 3 THEN 'locator' END END AS basis,
 CASE WHEN d.candidates>1 AND d.paired_candidates<>1 THEN d.candidate_keys
  ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)') END AS candidate_keys
FROM olds o
LEFT JOIN decided d ON d.old_key=o.old_key
