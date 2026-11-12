-- Fresh witness_key_map rows for live prior_witnesses keys that left appearance_records_resolved (ct-46f3).
-- Materialized once so witness_key_map's 1-hop carry and historical Senate keys read it without re-scanning
-- prior_witnesses or appearance_records_resolved.
WITH published_keys AS (
 SELECT DISTINCT witness_key FROM appearance_records_resolved
), prior_all AS (
 SELECT
  pw.witness_key AS old_key,
  pw.occasion,
  pw.source,
  coalesce(pw.package_id,'') AS package_key,
  lower(encode(pw.record_sha,'hex')) AS record_sha_hex,
  pw.source_locator,
  pw.name,
  pw.position,
  pw.organization,
  pw.on_behalf_of,
  pw.location,
  pw.panel,
  pw.panel_order,
  pw.display_order,
  coalesce(pw.listing_status,'listed') AS listing_status,
  pw.bioguide_id,
  coalesce(trim(regexp_replace(lower(pw.name),'[^\p{L}\p{N}]+',' ','g')),'') AS name_t,
  coalesce(trim(regexp_replace(lower(pw.organization),'[^\p{L}\p{N}]+',' ','g')),'') AS organization_t,
  coalesce(trim(regexp_replace(lower(pw.position),'[^\p{L}\p{N}]+',' ','g')),'') AS position_t
 FROM prior_witnesses pw
 WHERE pw.witness_key IS NOT NULL
), prior_ranked AS (
 SELECT *,
  row_number() OVER(
   PARTITION BY occasion,source,package_key,name_t,organization_t,position_t
   ORDER BY (listing_status='listed') DESC,panel_order ASC NULLS LAST,display_order ASC NULLS LAST,source_locator ASC,old_key ASC
  ) AS p_repeat_rank,
  count(*) OVER(
   PARTITION BY occasion,source,package_key,name_t,organization_t,position_t
  ) AS p_repeat_cnt
 FROM prior_all
), unmapped_raw AS (
 SELECT pw.*
 FROM published_keys pk
 RIGHT ANTI JOIN prior_ranked pw ON pk.witness_key=pw.old_key
), unmapped_words AS (
 SELECT u.*,
  array_except(string_to_array(trim(regexp_replace(regexp_replace(split_part(regexp_replace(
    lower(coalesce(u.name,'')),'\([^)]*\)',' ','g'),',',1),'[^a-z \-]+','','g'),'[ \-]+',' ','g')),' '),
   make_array('','mr','mrs','ms','miss','mx','dr','hon','honorable','the','rev','reverend','sen','senator','rep','representative',
    'gen','general','lt','lieutenant','col','colonel','maj','major','adm','admiral','vadm','radm','ltg','mg','bg','vice','rear',
    'capt','captain','sgt','sergeant','brigadier','chief','ambassador','secretary','judge','governor','mayor','professor','prof',
    'commissioner','chairman','chairwoman','chair','ranking','member','congressman','congresswoman','delegate',
    'jr','sr','ii','iii','iv','phd','md','mph','jd','rn','mba','dvm','esq','cpa','edd','dds','mpa','mpp','msw','ret',
    'usa','usn','usaf','usmc','uscg','ussf')) AS t
 FROM unmapped_raw u
), unmapped_keyed AS (
 SELECT *,cast(cardinality(t) AS BIGINT) AS n FROM unmapped_words
), unmapped_parted AS (
 SELECT *,n>=2 AND t[n-1] IN ('del','de','della','van','von','la','le','di','da','du','st','mac','mc','dos','das') AS particle
 FROM unmapped_keyed
), unmapped_named AS (
 SELECT old_key,occasion,source,package_key,record_sha_hex,source_locator,name,position,organization,
  on_behalf_of,location,panel,bioguide_id,name_t,organization_t,position_t,p_repeat_rank,p_repeat_cnt,
  CASE WHEN n=0 THEN NULL WHEN particle THEN concat(t[n-1],' ',t[n]) ELSE t[n] END AS family,
  CASE WHEN particle AND n>=3 THEN t[1] WHEN NOT particle AND n>=2 THEN t[1] END AS given
 FROM unmapped_parted
), unmapped_people AS (
 SELECT n.*,coalesce(k.formal,n.given) AS given_canon
 FROM person_nicknames k RIGHT JOIN unmapped_named n ON k.nick=n.given
), resolved_ranked AS (
 SELECT c.*,
  count(*) OVER(
   PARTITION BY c.occasion,c.source,c.package_key,c.name_t,c.organization_t,c.position_t
  ) AS c_repeat_cnt
 FROM appearance_records_resolved c
), locator_candidates AS (
 SELECT
  u.old_key,
  c.witness_key,
  u.family AS u_family,
  cp.family AS c_family,
  u.given AS u_given,
  cp.given AS c_given,
  u.given_canon AS u_given_canon,
  cp.given_canon AS c_given_canon
 FROM unmapped_people u
 JOIN appearance_records_resolved c
  ON (c.occasion=u.occasion OR u.package_key<>'')
  AND c.source=u.source AND c.package_key=u.package_key AND c.source_locator=u.source_locator
 JOIN appearance_people cp
  ON cp.record_sha_hex=c.record_sha_hex AND cp.source=c.source AND cp.ordinal=c.ordinal
 WHERE c.carry_tier='minted'
  AND u.name_t<>c.name_t
  AND coalesce(u.position,u.organization,u.bioguide_id) IS NOT NULL
  AND u.position_t=c.position_t AND u.organization_t=c.organization_t
  AND (u.on_behalf_of IS NOT DISTINCT FROM c.on_behalf_of)
  AND (u.location IS NOT DISTINCT FROM c.location)
  AND (u.panel IS NOT DISTINCT FROM c.panel)
  AND coalesce(u.bioguide_id,'')=coalesce(c.bioguide_id,'')
  AND u.family IS NOT NULL AND cp.family IS NOT NULL
), locator_family_ok AS (
 SELECT old_key,witness_key,u_given,c_given,u_given_canon,c_given_canon
 FROM locator_candidates
 WHERE u_family=c_family
  OR (length(u_family)>=5 AND length(c_family)>=4 AND abs(length(u_family)-length(c_family))<=1 AND levenshtein(u_family,c_family)<=1)
), locator_matched AS (
 SELECT DISTINCT old_key,witness_key FROM (
  SELECT old_key,witness_key
  FROM locator_family_ok
  WHERE u_given IS NULL OR c_given IS NULL OR u_given_canon=c_given_canon
   OR (length(u_given)>=3 AND length(c_given)>=3 AND substr(u_given,1,3)=substr(c_given,1,3))
   OR (length(u_given)=1 AND u_given=substr(c_given,1,1))
   OR (length(c_given)=1 AND c_given=substr(u_given,1,1))
  UNION ALL
  SELECT f.old_key,f.witness_key
  FROM locator_family_ok f
  JOIN person_given_matches gm ON gm.left_given=f.u_given AND gm.right_given=f.c_given
  WHERE f.u_given IS NOT NULL AND f.c_given IS NOT NULL
 )
), pairs AS (
 SELECT u.old_key,c.witness_key,1 AS tier,true AS paired
 FROM unmapped_people u
 JOIN resolved_ranked c
  ON c.source=u.source AND c.record_sha_hex=u.record_sha_hex AND c.source_locator=u.source_locator
 UNION ALL
 SELECT u.old_key,c.witness_key,2 AS tier,
  (u.p_repeat_cnt=c.c_repeat_cnt AND u.p_repeat_rank=c.occurrence_ordinal
   AND (coalesce(u.position,u.organization,u.on_behalf_of,u.bioguide_id) IS NOT NULL OR c.source_locator=u.source_locator)) AS paired
 FROM unmapped_people u
 JOIN resolved_ranked c
  ON (c.occasion=u.occasion OR u.package_key<>'')
  AND c.source=u.source AND c.package_key=u.package_key
  AND c.name_t=u.name_t AND c.organization_t=u.organization_t AND c.position_t=u.position_t
 WHERE u.name_t<>''
 UNION ALL
 SELECT old_key,witness_key,3 AS tier,true AS paired
 FROM locator_matched
), per_candidate AS (
 SELECT old_key,witness_key,min(tier) AS tier,bool_or(paired) AS paired
 FROM pairs
 GROUP BY old_key,witness_key
), best AS (
 SELECT *,min(tier) OVER(PARTITION BY old_key) AS best_tier
 FROM per_candidate
), grouped AS (
 SELECT
  old_key,
  min(tier) AS tier,
  count(witness_key) AS candidates,
  count(witness_key) FILTER (WHERE paired) AS paired_candidates,
  min(witness_key) FILTER (WHERE paired) AS paired_key,
  array_agg(witness_key ORDER BY witness_key) AS candidate_keys
 FROM best
 WHERE tier=best_tier
 GROUP BY old_key
), with_target_claims AS (
 SELECT *,
  CASE WHEN paired_candidates=1 THEN count(*) OVER(PARTITION BY paired_key) ELSE 0 END AS target_claims
 FROM grouped
)
SELECT
 u.old_key,
 CASE WHEN d.paired_candidates=1 AND d.target_claims=1 THEN d.paired_key END AS witness_key,
 CASE
  WHEN d.paired_candidates=1 AND d.target_claims=1 THEN 'unambiguous'
  WHEN d.candidates>1 THEN 'ambiguous'
  ELSE 'unresolved'
 END AS status,
 CASE
  WHEN (d.paired_candidates=1 AND d.target_claims=1) OR d.candidates>1
   THEN CASE d.tier WHEN 1 THEN 'occurrence' WHEN 2 THEN 'content' WHEN 3 THEN 'locator' END
 END AS basis,
 CASE
  WHEN d.candidates>1 AND NOT (d.paired_candidates=1 AND d.target_claims=1) THEN d.candidate_keys
  ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
 END AS candidate_keys,
 u.occasion,
 u.source
FROM unmapped_people u
JOIN with_target_claims d ON d.old_key=u.old_key
WHERE d.candidates>=1
