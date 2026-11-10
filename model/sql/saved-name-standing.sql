-- DM 7.5 name standing (ct-h8dr, ct-yuf0): which of a body's names may name the document.
-- An official name (its filename reading is valid: a House or GovInfo convention name) leads, unless
-- it is contradicted: it states a kind, a committee's own name for the same bytes states a kind, and
-- no committee name states the official name's. A contradicted name in one of the House repository's
-- meeting-document slots (biography, disclosure, statement, supporting-material) gives way to a
-- committee name that states a kind: read against the documents, those slot labels were wrong or said
-- less than the committee's name in 144 of 158 such pairs (54 testimonies filed under Bio and
-- support-document names, 2026-11-10). A contradicted official name of any other kind (a GovInfo
-- hearing beside a committee "transcript") is left where saved-file order puts it: 11 of 15 read were
-- right, and the choice is the owner's (ct-h8dr). A name states the families its copy would give the
-- document (a linked name's included). Only a named real file with an address or a member path can
-- name a body. Rows: standing 0, an official name not contradicted; 1, a committee name that states a
-- kind beside an official slot name; every other file has no row and keeps saved-file order.
-- One join, then running windows over one row per stated family (no whole-partition WindowAggExec, no
-- per-group lists): three sorts of about one row per named copy, n log n.
WITH said AS (
 -- IS NOT DISTINCT FROM true, not coalesce or IS TRUE: on a lake-backed build coalesce carries the
 -- reading column's Parquet field id into an expression the planner reuses, and IS TRUE differs in
 -- nullability; either way the pinned engine refuses the plan (logical and physical schemas disagree).
 SELECT m.component,m.body_sha,m.source_id,f.valid IS NOT DISTINCT FROM true AS official,
  unnest(CASE WHEN f.document_family_status='completed' AND coalesce(array_length(f.document_family),0)>0
   THEN f.document_family ELSE make_array('') END) AS family
 FROM (SELECT component,body_sha,source_id FROM document_members
  WHERE is_real_file AND coalesce(filename,'')<>'' AND (source_url IS NOT NULL OR coalesce(archive_member,false))) m
 JOIN source_filename_readings f ON f.source_id=m.source_id
), judged AS (
 -- false sorts first, so each first_value asks whether the partition holds a slot (or a committee) row.
 -- source_id keeps the first two orders from being each other's reverse: the planner would answer one
 -- from the other's sort with an unbounded-following frame, a whole-partition WindowAggExec.
 SELECT component,source_id,official,family,
  first_value(slot) OVER (PARTITION BY component,body_sha ORDER BY slot DESC,source_id
   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS slot_named,
  NOT first_value(official) OVER (PARTITION BY component,body_sha ORDER BY official,source_id
   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS committee_speaks,
  NOT first_value(official) OVER (PARTITION BY component,body_sha,family ORDER BY official
   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS committee_agrees
 FROM (SELECT *,official AND family IN ('biography','disclosure','statement','supporting-material') AS slot
  FROM said WHERE official OR family<>'')
)
SELECT component,source_id,CASE WHEN official THEN 0 ELSE 1 END AS standing
FROM judged WHERE official OR slot_named
GROUP BY component,source_id,official
HAVING NOT official OR NOT bool_or(family<>'' AND committee_speaks) OR bool_or(committee_agrees)
