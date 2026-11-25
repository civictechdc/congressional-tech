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
  cast(sum(CASE WHEN wt.score=wt.top_score THEN 1 ELSE 0 END) OVER (PARTITION BY wt.bag_key) AS BIGINT) AS top_count
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
  WHEN s.score=s.top_score AND s.top_count=1 AND s.top_score>=90.0 THEN 'auto_accept'
  WHEN coalesce(d.has_same,false) OR coalesce(d.has_unsure,false) THEN 'decided'
  WHEN s.score>=80.0 THEN 'review'
  ELSE 'below_threshold'
 END AS link_status
FROM bag_wd_decisions d
RIGHT JOIN scored s ON s.bag_key=d.bag_key AND s.qid=d.qid
