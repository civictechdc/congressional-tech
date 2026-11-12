-- Link present Senate committee hearing pages (senate_page) to canonical meetings (ct-j2yo, ct-uul8).
-- Scores senate_page_candidates against known meeting surnames (Congress.gov and vetted single-event prints)
-- and substantive title/slug word overlap.
WITH meeting_known_people AS (
 SELECT event_id,array_distinct(array_agg(family)) AS families
 FROM (
  SELECT pml.event_id,ap.family
  FROM package_meeting_links pml
  JOIN appearance_people ap ON ap.source='mods' AND ap.package_id=pml.package_id
  WHERE pml.witness_eligible AND ap.family IS NOT NULL AND NOT ap.statement
  UNION ALL
  SELECT ap.event_id,ap.family
  FROM appearance_people ap
  WHERE ap.source='congress_gov' AND ap.event_id IS NOT NULL AND ap.family IS NOT NULL AND NOT ap.statement
 ) p
 GROUP BY event_id
), dated_candidates AS (
 SELECT
  s.record_sha_hex,
  s.source_url,
  s.banking_hearing_url,
  s.event_id,
  s.single_url_on_date,
  s.single_event_on_date,
  s.requires_overlap,
  coalesce(cast(cardinality(array_intersect(s.families,mp.families)) AS BIGINT),cast(0 AS BIGINT)) AS shared_surnames,
  s.shared_words
 FROM meeting_known_people mp
 RIGHT JOIN senate_page_candidates s ON mp.event_id=s.event_id
), dated_scored AS (
 SELECT
  record_sha_hex,
  source_url,
  banking_hearing_url,
  event_id,
  shared_surnames,
  shared_surnames*cast(100 AS BIGINT)+shared_words AS score
 FROM dated_candidates
 WHERE (single_event_on_date AND single_url_on_date AND NOT requires_overlap)
  OR shared_surnames>0
  OR shared_words>=2
), sha_ranked AS (
 SELECT
  record_sha_hex,
  source_url,
  banking_hearing_url,
  event_id,
  shared_surnames,
  score,
  row_number() OVER (PARTITION BY record_sha_hex ORDER BY score DESC,event_id ASC) AS sha_rn,
  lead(score) OVER (PARTITION BY record_sha_hex ORDER BY score DESC,event_id ASC) AS next_sha_score
 FROM dated_scored
), unique_sha_winners AS (
 SELECT record_sha_hex,source_url,banking_hearing_url,event_id,shared_surnames,score
 FROM sha_ranked
 WHERE sha_rn=1 AND (next_sha_score IS NULL OR next_sha_score<score)
), event_ranked AS (
 SELECT
  record_sha_hex,
  source_url,
  banking_hearing_url,
  event_id,
  shared_surnames,
  score,
  first_value(score) OVER (PARTITION BY event_id ORDER BY score DESC,record_sha_hex ASC) AS max_event_score
 FROM unique_sha_winners
), event_top_winners AS (
 SELECT
  record_sha_hex,
  event_id,
  banking_hearing_url,
  first_value(source_url) OVER (PARTITION BY event_id ORDER BY source_url ASC,record_sha_hex ASC)=
   first_value(source_url) OVER (PARTITION BY event_id ORDER BY source_url DESC,record_sha_hex ASC)
   OR first_value(shared_surnames) OVER (PARTITION BY event_id ORDER BY shared_surnames DESC,record_sha_hex ASC)>0 AS keep_event
 FROM event_ranked
 WHERE score=max_event_score
)
SELECT record_sha_hex,event_id,banking_hearing_url
FROM event_top_winners
WHERE keep_event
