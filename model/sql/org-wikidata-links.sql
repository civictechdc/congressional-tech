-- Score retained Wikidata reconciliation candidates per org bag (ct-39u8).
-- Auto-accept: unique top candidate scoring >= 90 not blocked by a different decision on (bag, Q).
-- Review band: other candidates scoring >= 80 (including top ties and runner-ups), never auto-linked.
-- Stacks with Phase 2 org_bag_registry_matches (ct-w34j) in archive_model.py anchor/edge assembly.
WITH bag_receipts AS (
 SELECT
  w.bag_key,
  w.receipt_sha,
  w.receipt_key,
  w.retrieved_at,
  row_number() OVER (
   PARTITION BY w.bag_key
   ORDER BY w.retrieved_at DESC NULLS LAST,w.receipt_key DESC,w.receipt_sha DESC
  ) AS rn
 FROM wikidata_reconcile_bodies w
), latest_receipt AS (
 SELECT
  bag_key,
  receipt_sha,
  receipt_key,
  retrieved_at
 FROM bag_receipts
 WHERE rn=1
), latest_candidates AS (
 SELECT
  w.bag_key,
  w.qid,
  w.candidate_name,
  w.candidate_description,
  w.score,
  w.api_match,
  w.cand_types,
  w.receipt_sha,
  w.receipt_key,
  w.retrieved_at,
  row_number() OVER (
   PARTITION BY w.bag_key,w.qid
   ORDER BY w.score DESC,w.api_match DESC,w.candidate_name ASC NULLS LAST
  ) AS cand_rn
 FROM latest_receipt lr
 JOIN wikidata_reconcile_bodies w
  ON w.bag_key=lr.bag_key AND w.receipt_sha=lr.receipt_sha
), deduped AS (
 SELECT
  c.bag_key,
  b.appearance_count,
  b.l2_text,
  b.display_text,
  c.qid,
  c.candidate_name,
  c.candidate_description,
  c.score,
  c.api_match,
  c.cand_types,
  c.receipt_sha,
  c.receipt_key,
  c.retrieved_at
 FROM latest_candidates c
 JOIN org_bags b ON b.bag_key=c.bag_key
 WHERE c.cand_rn=1
), with_top AS (
 SELECT
  d.*,
  max(d.score) OVER (PARTITION BY d.bag_key) AS top_score
 FROM deduped d
), scored AS (
 SELECT
  wt.*,
  cast(sum(CASE WHEN wt.score=wt.top_score THEN 1 ELSE 0 END) OVER (PARTITION BY wt.bag_key) AS BIGINT) AS top_count,
  (
   coalesce(cardinality(wt.cand_types),0)>0
   AND NOT array_has_any(wt.cand_types,make_array(
    'Q5','Q3947','Q3257686','Q11862829','Q210588','Q3055347','Q4167410','Q13442814',
    'Q571','Q7725634','Q11424','Q482994','Q7366','Q1357601','Q4164871'
   ))
   AND NOT (
    array_has_any(wt.cand_types,make_array('Q515','Q1093829','Q486972','Q532','Q3957','Q1549591'))
    AND NOT array_has_any(wt.cand_types,make_array('Q43229','Q327333','Q106514250','Q2659904','Q7210356','Q2221906'))
    AND NOT regexp_like(coalesce(wt.l2_text,''),'^(?:city|town|village)\s+of\s+')
   )
   AND NOT array_has_any(
    array_except(
     string_to_array(trim(regexp_replace(replace(lower(coalesce(wt.candidate_name,'')),'u.k.','uk'),'[^a-z0-9]+',' ','g')),' '),
     string_to_array(trim(regexp_replace(replace(lower(coalesce(wt.display_text,'')||' '||coalesce(wt.l2_text,'')),'u.k.','uk'),'[^a-z0-9]+',' ','g')),' ')
    ),
    make_array('uk','canada','australia','india','ireland','germany','france','japan','china','mexico','brazil','europe')
   )
  ) AS auto_eligible
 FROM with_top wt
), bag_wd_decisions AS (
 SELECT
  CASE WHEN subject_kind='bag' THEN subject_key ELSE object_key END AS bag_key,
  CASE WHEN subject_kind='wikidata' THEN subject_key ELSE object_key END AS qid,
  bool_or(verdict='different') AS blocked_by_different,
  bool_or(verdict='same') AS has_same,
  bool_or(verdict='unsure') AS has_unsure
 FROM org_decisions_current
 WHERE resolution_status IN ('live','remapped')
  AND verdict IN ('same','different','unsure')
  AND ((subject_kind='bag' AND object_kind='wikidata')
   OR (subject_kind='wikidata' AND object_kind='bag'))
 GROUP BY 1,2
)
SELECT
 s.bag_key,
 s.appearance_count,
 s.l2_text,
 s.display_text,
 s.qid,
 s.candidate_name,
 s.candidate_description,
 s.score,
 s.api_match,
 s.cand_types,
 s.top_score,
 s.top_count,
 s.receipt_sha,
 s.receipt_key,
 s.retrieved_at,
 coalesce(d.blocked_by_different,false) AS blocked_by_different,
 coalesce(d.has_same,false) AS decided_same,
 coalesce(d.has_unsure,false) AS decided_unsure,
 CASE
  WHEN coalesce(d.blocked_by_different,false) THEN 'blocked_different'
  WHEN s.score=s.top_score AND s.top_count=1 AND s.top_score>=90.0 AND s.auto_eligible THEN 'auto_accept'
  WHEN coalesce(d.has_same,false) OR coalesce(d.has_unsure,false) THEN 'decided'
  WHEN s.score>=80.0 THEN 'review'
  ELSE 'below_threshold'
 END AS link_status
FROM bag_wd_decisions d
RIGHT JOIN scored s ON s.bag_key=d.bag_key AND s.qid=d.qid
