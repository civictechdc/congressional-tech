-- Link present Senate committee hearing pages (senate_page) to canonical meetings (ct-j2yo, ct-uul8).
-- Scores senate_page_candidates against known meeting surnames (Congress.gov and vetted single-event prints)
-- and substantive title/slug word overlap.
WITH meeting_known_people AS (
 SELECT p.event_id,array_distinct(array_agg(p.family)) AS families
 FROM (SELECT DISTINCT event_id FROM senate_page_candidates) e
 JOIN (
  SELECT pml.event_id,ap.family
  FROM package_meeting_links pml
  JOIN appearance_people ap ON ap.source='mods' AND ap.package_id=pml.package_id
  WHERE pml.witness_eligible AND ap.family IS NOT NULL AND NOT ap.statement
  UNION ALL
  SELECT ap.event_id,ap.family
  FROM appearance_people ap
  WHERE ap.source='congress_gov' AND ap.event_id IS NOT NULL AND ap.family IS NOT NULL AND NOT ap.statement
 ) p ON e.event_id=p.event_id
 GROUP BY p.event_id
), dated_candidates AS (
 SELECT
  s.record_sha_hex,
  s.page_key,
  s.banking_hearing_url,
  s.event_id,
  s.single_page_on_date,
  s.single_event_on_date,
  s.requires_overlap,
  coalesce(cast(cardinality(array_intersect(s.families,mp.families)) AS BIGINT),cast(0 AS BIGINT)) AS shared_surnames,
  s.shared_words
 -- The build side now contains at most one surname array per candidate event.
 FROM meeting_known_people mp
 RIGHT JOIN senate_page_candidates s ON mp.event_id=s.event_id
), body_scores AS (
 SELECT record_sha_hex,page_key,banking_hearing_url,event_id,shared_surnames,
  CASE WHEN (single_event_on_date AND single_page_on_date AND NOT requires_overlap)
    OR shared_surnames>0 OR shared_words>=2
   THEN shared_surnames*cast(100 AS BIGINT)+shared_words END AS body_score
 FROM dated_candidates
), sha_ranked AS (
 SELECT *,
  first_value(body_score) OVER body_rank AS best_body_score,
  row_number() OVER body_rank AS sha_rn,
  lead(body_score) OVER body_rank AS next_sha_score
 FROM body_scores
 WINDOW body_rank AS (PARTITION BY record_sha_hex ORDER BY body_score DESC NULLS LAST,event_id)
), page_scores AS (
 -- Only a body with a unique best event can establish the page's score. Keep
 -- uncorroborated copies as well so they can inherit a winning page's link.
 SELECT *,first_value(body_score) OVER (PARTITION BY event_id,page_key
  ORDER BY body_score DESC NULLS LAST,record_sha_hex) AS page_score
 FROM sha_ranked
 WHERE best_body_score IS NULL OR (sha_rn=1 AND (next_sha_score IS NULL OR next_sha_score<body_score))
), event_ranked AS (
 SELECT *,first_value(page_score) OVER (PARTITION BY event_id ORDER BY page_score DESC) AS best_score
 FROM page_scores
 WHERE page_score IS NOT NULL
), top_pages AS (
 SELECT *,
  first_value(page_key) OVER (PARTITION BY event_id ORDER BY page_key ASC,record_sha_hex)=
   first_value(page_key) OVER (PARTITION BY event_id ORDER BY page_key DESC,record_sha_hex) AS sole_page,
  first_value(shared_surnames) OVER (PARTITION BY event_id
   ORDER BY body_score DESC NULLS LAST,shared_surnames DESC) AS top_surnames
 FROM event_ranked
 WHERE page_score=best_score
)
SELECT record_sha_hex,min(event_id) AS event_id,min(banking_hearing_url) AS banking_hearing_url
FROM top_pages
-- Only a sole winning page extends its link to weaker copies. For a tie between
-- distinct pages, retain the existing exception for surname-corroborated top scores.
WHERE sole_page OR (body_score=best_score AND top_surnames>0)
-- A copy with no corroboration can inherit at most one meeting.
GROUP BY record_sha_hex
HAVING min(event_id)=max(event_id)
