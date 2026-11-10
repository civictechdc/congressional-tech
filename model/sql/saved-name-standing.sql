-- DM 7.5 name standing (ct-h8dr, ct-yuf0): which of a body's names may name the document.
-- An official name (its filename reading is valid: a House or GovInfo convention name) leads, unless
-- it is contradicted: it states a kind, a committee's own name for the same bytes states a kind, and
-- no committee name states the official name's. Three rules settle a contradiction; each held without
-- exception in the documents read (2026-11-10, the 343 non-slot names one by one, ct-h8dr):
-- - a GovInfo printed hearing is also the hearing's transcript and its nomination record (132 read
--   or GPO's own bytes), and an official vote record is also the amendment it tallies (57 read): the
--   official name states those kinds too and leads, after an official name a committee name agrees
--   with outright (6 printed hearings also carry a House transcript name that leads);
-- - a contradicted name in one of the House repository's meeting-document slots (biography,
--   disclosure, statement, supporting-material) or the generic House name (committee-document: a cover
--   page or table of contents) gives way to a committee name that states a kind: the slot labels were
--   wrong or said less in 144 of 158 pairs read (54 testimonies filed under Bio and support-document
--   names), and all 21 generic names read stood beside the committee's hearing notice.
-- A body the review decided one by one (saved_name_decisions, keyed by its sha256) takes that decision
-- instead of any rule: official, or committee (a committee name that states a kind); undecided and
-- neither keep saved-file order. Any other contradicted official name keeps saved-file order too.
-- A name states the families its copy would give the document (a linked name's included). Only a
-- named real file with an address or a member path can name a body. Rows: standing 0, an official
-- name not contradicted; 1, an official name a rule or the review settles, or a committee name a rule
-- or the review prefers; every other file has no row and keeps saved-file order.
-- One join, then running windows over one row per stated family (no whole-partition WindowAggExec, no
-- per-group lists): three sorts of about one row per named copy, n log n. The registry is the hash
-- build side of its join.
WITH named AS (
 -- IS NOT DISTINCT FROM true, not coalesce or IS TRUE: on a lake-backed build coalesce carries the
 -- reading column's Parquet field id into an expression the planner reuses, and IS TRUE differs in
 -- nullability; either way the pinned engine refuses the plan (logical and physical schemas disagree).
 SELECT m.component,m.body_sha,m.source_id,v.decision,f.valid IS NOT DISTINCT FROM true AS official,
  CASE WHEN f.document_family_status='completed' AND coalesce(array_length(f.document_family),0)>0
   THEN f.document_family ELSE make_array('') END AS stated
 FROM saved_name_decisions v RIGHT JOIN (SELECT component,body_sha,source_id FROM document_members
  WHERE is_real_file AND coalesce(filename,'')<>'' AND (source_url IS NOT NULL OR coalesce(archive_member,false))) m
  ON v.body_sha=m.body_sha
 JOIN source_filename_readings f ON f.source_id=m.source_id
), said AS (
 -- implied: a family the official name states by rule, not by its own reading.
 SELECT component,body_sha,source_id,decision,official,family,official AND NOT array_has(stated,family) AS implied
 FROM (SELECT *,unnest(CASE WHEN NOT official THEN stated
   WHEN array_has(stated,'published-hearing') THEN array_concat(stated,make_array('transcript','nomination'))
   WHEN array_has(stated,'vote-record') THEN array_concat(stated,make_array('amendment')) ELSE stated END) AS family
  FROM named)
 WHERE official OR family<>''
), judged AS (
 -- false sorts first, so each first_value asks whether the partition holds a slot (or a committee) row.
 -- source_id keeps the first two orders from being each other's reverse: the planner would answer one
 -- from the other's sort with an unbounded-following frame, a whole-partition WindowAggExec.
 SELECT component,source_id,decision,official,family,implied,
  first_value(slot) OVER (PARTITION BY component,body_sha ORDER BY slot DESC,source_id
   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS slot_named,
  NOT first_value(official) OVER (PARTITION BY component,body_sha ORDER BY official,source_id
   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS committee_speaks,
  NOT first_value(official) OVER (PARTITION BY component,body_sha,family ORDER BY official
   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS committee_agrees
 FROM (SELECT *,official AND family IN ('biography','disclosure','statement','supporting-material','committee-document') AS slot
  FROM said)
)
SELECT component,source_id,standing FROM (
 SELECT component,source_id,CASE
  WHEN NOT official THEN CASE WHEN max(decision)='committee' OR (max(decision) IS NULL AND bool_or(slot_named)) THEN 1 END
  WHEN NOT bool_or(family<>'' AND committee_speaks) OR bool_or(committee_agrees AND NOT implied) THEN 0
  WHEN max(decision)='official' OR (max(decision) IS NULL AND bool_or(committee_agrees AND implied)) THEN 1 END AS standing
 FROM judged GROUP BY component,source_id,official)
WHERE standing IS NOT NULL
