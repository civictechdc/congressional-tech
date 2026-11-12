-- Which meetings each print records (ct-dx22, ct-uul8), among the meetings held on one of its days:
-- 1. When both sides carry official witness rosters (house_xml or congress_gov), the people decide: at least
--    half of the shorter list (and two people when both list two or more) is the same person (as in
--    witness-precedence.sql: family name, then agreeing given names).
--    A GovInfo <eventId> never vetoes (it is wrong on 29369's print) and titles are not consulted
--    ("PENDING LEGISLATION"; boilerplate Armed Services titles fit many hearings).
-- 2. When no official roster exists (Congress.gov lists no witnesses for Senate hearings), a resolved Senate
--    committee hearing page (senate_page_prelim_links) whose witnesses agree by the same rule corroborates
--    prints whose short GPO title ("LEGISLATIVE HEARING TO REVIEW S. 1462...") misses the long Daily Digest
--    statutory title, without vetoing nomination prints whose MODS lists only Congressional introducers.
-- 3. Otherwise the title decides: half the shorter title's substantive words (3+ characters, not stop
--    words) shared. "U.S. Cyber Diplomacy" shares only letters with "Assessing the U.S.-Qatar Relationship".
-- When a print agrees with several same-day meetings, a meeting that did not sit (a superseded duplicate
-- such as 105066, re-entered as 105084) yields to one that did, and witness agreement beats title-only overlap.
-- named records whether the print states this meeting's eventId (null when it states none).
WITH prints_raw AS (
 SELECT package_id,unnest(held_dates) AS day,named_meetings,
  array_distinct(array_except(string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words
 FROM package_mods_facts
), prints AS (
 SELECT package_id,day,named_meetings,words
 FROM (
  SELECT package_id,day,named_meetings,words,
   row_number() OVER(PARTITION BY package_id,day ORDER BY package_id) AS rn
  FROM prints_raw
  WHERE day IS NOT NULL
 )
 WHERE rn=1
), meetings AS (
 SELECT event_id,cast(meeting_date AS VARCHAR) AS day,coalesce(not_held,false) AS not_held,
  array_distinct(array_except(string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words
 FROM meetings_resolved WHERE meeting_date IS NOT NULL
), candidates AS (
 SELECT p.package_id,m.event_id,m.day,m.not_held,p.named_meetings,
  least(cast(cardinality(p.words) AS BIGINT),cast(cardinality(m.words) AS BIGINT))>0
   AND 2*cast(cardinality(array_intersect(p.words,m.words)) AS BIGINT)>=least(cast(cardinality(p.words) AS BIGINT),cast(cardinality(m.words) AS BIGINT)) AS title_agrees,
  cast(cardinality(array_intersect(p.words,m.words)) AS DOUBLE)/cast(greatest(cast(1 AS BIGINT),least(cast(cardinality(p.words) AS BIGINT),cast(cardinality(m.words) AS BIGINT))) AS DOUBLE) AS title_score
 FROM prints p JOIN meetings m ON p.day=m.day
), print_people AS (
 SELECT DISTINCT package_id,family,given,given_canon FROM appearance_people
 WHERE source='mods' AND NOT statement AND family IS NOT NULL AND package_id IS NOT NULL
), all_meeting_people AS (
 SELECT DISTINCT
  CASE WHEN ap.source='senate_page' THEN l.l_event_id ELSE ap.event_id END AS event_id,
  CASE WHEN ap.source='senate_page' THEN 'senate' ELSE 'official' END AS kind,
  ap.family,ap.given,ap.given_canon
 FROM (SELECT record_sha_hex,event_id AS l_event_id FROM senate_page_prelim_links) l
 RIGHT JOIN appearance_people ap ON ap.source='senate_page' AND ap.record_sha_hex=l.record_sha_hex
 WHERE NOT ap.statement AND ap.family IS NOT NULL
  AND (
   (ap.source IN ('house_xml','congress_gov') AND ap.event_id IS NOT NULL)
   OR (ap.source='senate_page' AND l.l_event_id IS NOT NULL)
  )
), print_counts AS (
 SELECT package_id AS pc_package_id,count(*) AS pc_n FROM print_people GROUP BY package_id
), all_meeting_counts AS (
 SELECT event_id AS mc_event_id,
  nullif(count(*) FILTER (WHERE kind='official'),0) AS mc_official_n,
  nullif(count(*) FILTER (WHERE kind='senate'),0) AS mc_senate_n
 FROM all_meeting_people GROUP BY event_id
), shared_by_kind AS (
 -- Slim pairs only: people rows carry no titles, so the join stays small.
 SELECT c.package_id AS sbk_package_id,c.event_id AS sbk_event_id,
  count(DISTINCT CASE WHEN b.kind='official' THEN concat(a.family,'|',coalesce(a.given,'')) END) AS shared_official_n,
  count(DISTINCT CASE WHEN b.kind='senate' THEN concat(a.family,'|',coalesce(a.given,'')) END) AS shared_senate_n
 FROM candidates c
 JOIN print_people a ON a.package_id=c.package_id
 JOIN all_meeting_people b ON b.event_id=c.event_id
 -- The same person as in witness-precedence.sql: family name, then agreeing given names.
 WHERE (a.family=b.family OR (length(a.family)>=5 AND levenshtein(a.family,b.family)<=1))
  AND (a.given IS NULL OR b.given IS NULL OR a.given_canon=b.given_canon
   OR (length(a.given)>=3 AND length(b.given)>=3 AND substr(a.given,1,3)=substr(b.given,1,3))
   OR (length(a.given)=1 AND a.given=substr(b.given,1,1)) OR (length(b.given)=1 AND b.given=substr(a.given,1,1)))
 GROUP BY c.package_id,c.event_id
), decided AS (
 SELECT c.package_id,c.event_id,c.day,c.not_held,c.named_meetings,
  -- Half the shorter list, and at least two people when both lists have two: one shared family name is chance.
  CASE
   WHEN pc.pc_n IS NOT NULL AND mc.mc_official_n IS NOT NULL THEN 2*coalesce(sbk.shared_official_n,0)>=least(pc.pc_n,mc.mc_official_n) AND coalesce(sbk.shared_official_n,0)>=least(cast(2 AS BIGINT),pc.pc_n,mc.mc_official_n)
   WHEN pc.pc_n IS NOT NULL AND mc.mc_senate_n IS NOT NULL AND 2*coalesce(sbk.shared_senate_n,0)>=least(pc.pc_n,mc.mc_senate_n) AND coalesce(sbk.shared_senate_n,0)>=least(cast(2 AS BIGINT),pc.pc_n,mc.mc_senate_n) THEN true
   ELSE coalesce(c.title_agrees,false)
  END AS agrees,
  CASE
   WHEN pc.pc_n IS NOT NULL AND mc.mc_official_n IS NOT NULL THEN 'witnesses'
   WHEN pc.pc_n IS NOT NULL AND mc.mc_senate_n IS NOT NULL AND 2*coalesce(sbk.shared_senate_n,0)>=least(pc.pc_n,mc.mc_senate_n) AND coalesce(sbk.shared_senate_n,0)>=least(cast(2 AS BIGINT),pc.pc_n,mc.mc_senate_n) THEN 'witnesses'
   ELSE 'title'
  END AS basis,
  CASE
   WHEN pc.pc_n IS NOT NULL AND mc.mc_official_n IS NOT NULL THEN cast(coalesce(sbk.shared_official_n,0) AS DOUBLE)/cast(least(pc.pc_n,mc.mc_official_n) AS DOUBLE)
   WHEN pc.pc_n IS NOT NULL AND mc.mc_senate_n IS NOT NULL AND 2*coalesce(sbk.shared_senate_n,0)>=least(pc.pc_n,mc.mc_senate_n) AND coalesce(sbk.shared_senate_n,0)>=least(cast(2 AS BIGINT),pc.pc_n,mc.mc_senate_n) THEN cast(coalesce(sbk.shared_senate_n,0) AS DOUBLE)/cast(least(pc.pc_n,mc.mc_senate_n) AS DOUBLE)
   ELSE coalesce(c.title_score,0.0)
  END AS score
 FROM shared_by_kind sbk
 RIGHT JOIN (
  all_meeting_counts mc
  RIGHT JOIN (
   print_counts pc
   RIGHT JOIN candidates c ON pc.pc_package_id=c.package_id
  ) ON mc.mc_event_id=c.event_id
 ) ON sbk.sbk_package_id=c.package_id AND sbk.sbk_event_id=c.event_id
), agreeing AS (
 -- Ordered windows (first_value), not unbounded aggregates over the partition (join audit).
 SELECT *,
  CASE WHEN basis='witnesses' THEN 1 ELSE 0 END AS basis_rank,
  NOT first_value(not_held) OVER(PARTITION BY package_id,day ORDER BY not_held ASC,event_id ASC) AS some_sat
 FROM decided WHERE agrees
), sat AS (
 SELECT *,
  first_value(basis_rank) OVER(PARTITION BY package_id,day ORDER BY basis_rank DESC,score DESC,event_id ASC) AS best_basis,
  first_value(score) OVER(PARTITION BY package_id,day ORDER BY basis_rank DESC,score DESC,event_id ASC) AS best_score
 FROM agreeing WHERE NOT (not_held AND some_sat)
)
-- One print records one meeting a day: of several same-day meetings that agree (a hearing and a markup of
-- the same bills, 100692 and 100693), the best match keeps it; ties stay.
SELECT package_id,event_id,basis,
 CASE WHEN coalesce(cast(cardinality(named_meetings) AS BIGINT),0)>0 THEN array_has(named_meetings,event_id) END AS named
FROM sat WHERE basis_rank=best_basis AND score=best_score
