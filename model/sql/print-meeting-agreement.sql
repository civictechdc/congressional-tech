-- Which meetings each print records (ct-dx22), among the meetings held on one of its days:
-- 1. When both sides list witnesses, the people decide: at least half of the shorter list (and two people
--    when both list two or more) is the same person (as in witness-precedence.sql: family name, then agreeing
--    given names).
--    A GovInfo <eventId> never vetoes (it is wrong on 29369's print) and titles are not consulted
--    ("PENDING LEGISLATION"; boilerplate Armed Services titles fit many hearings).
-- 2. Otherwise the title decides: half the shorter title's substantive words (3+ characters, not stop
--    words) shared. "U.S. Cyber Diplomacy" shares only letters with "Assessing the U.S.-Qatar Relationship".
-- When a print agrees with several same-day meetings, a meeting that did not sit (a superseded duplicate
-- such as 105066, re-entered as 105084) yields to one that did.
-- named records whether the print states this meeting's eventId (null when it states none).
WITH prints AS (
 SELECT package_id,unnest(held_dates) AS day,array_distinct(array_except(string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words FROM package_mods_facts
), meetings AS (
 SELECT event_id,cast(meeting_date AS VARCHAR) AS day,coalesce(not_held,false) AS not_held,array_distinct(array_except(string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words
 FROM meetings_resolved WHERE meeting_date IS NOT NULL
), candidates AS (
 SELECT DISTINCT p.package_id,m.event_id,m.day,m.not_held FROM prints p JOIN meetings m ON p.day=m.day
), print_people AS (
 SELECT DISTINCT package_id,family,given,given_canon FROM appearance_people
 WHERE source='mods' AND NOT statement AND family IS NOT NULL AND package_id IS NOT NULL
), meeting_people AS (
 SELECT DISTINCT event_id,family,given,given_canon FROM appearance_people
 WHERE source IN ('house_xml','congress_gov') AND NOT statement AND family IS NOT NULL AND event_id IS NOT NULL
), print_counts AS (SELECT package_id,count(*) AS n FROM print_people GROUP BY package_id
), meeting_counts AS (SELECT event_id,count(*) AS n FROM meeting_people GROUP BY event_id
), shared AS (
 -- Slim pairs only: people rows carry no titles, so the join stays small.
 SELECT c.package_id,c.event_id,count(DISTINCT concat(a.family,'|',coalesce(a.given,''))) AS n
 FROM candidates c
 JOIN print_people a ON a.package_id=c.package_id
 JOIN meeting_people b ON b.event_id=c.event_id
 -- The same person as in witness-precedence.sql: family name, then agreeing given names.
 WHERE (a.family=b.family OR (length(a.family)>=5 AND levenshtein(a.family,b.family)<=1))
  AND (a.given IS NULL OR b.given IS NULL OR a.given_canon=b.given_canon
   OR (length(a.given)>=3 AND length(b.given)>=3 AND substr(a.given,1,3)=substr(b.given,1,3))
   OR (length(a.given)=1 AND a.given=substr(b.given,1,1)) OR (length(b.given)=1 AND b.given=substr(a.given,1,1)))
 GROUP BY c.package_id,c.event_id
), titled AS (
 -- Titles are compared only for pairs where a side lists no witnesses.
 SELECT DISTINCT c.package_id,c.event_id,
  least(cardinality(p.words),cardinality(m.words))>0
   AND 2*cardinality(array_intersect(p.words,m.words))>=least(cardinality(p.words),cardinality(m.words)) AS agrees,
  cast(cardinality(array_intersect(p.words,m.words)) AS DOUBLE)/greatest(1,least(cardinality(p.words),cardinality(m.words))) AS score
 FROM candidates c
 LEFT JOIN print_counts pc ON pc.package_id=c.package_id
 LEFT JOIN meeting_counts mc ON mc.event_id=c.event_id
 JOIN (SELECT DISTINCT package_id,words FROM prints) p ON p.package_id=c.package_id
 JOIN meetings m ON m.event_id=c.event_id
 WHERE pc.n IS NULL OR mc.n IS NULL
), decided AS (
 SELECT c.package_id,c.event_id,c.day,c.not_held,f.named_meetings,
  -- Half the shorter list, and at least two people when both lists have two: one shared family name is chance.
  CASE WHEN pc.n IS NOT NULL AND mc.n IS NOT NULL THEN 2*coalesce(s.n,0)>=least(pc.n,mc.n) AND coalesce(s.n,0)>=least(2,pc.n,mc.n)
   ELSE coalesce(t.agrees,false) END AS agrees,
  CASE WHEN pc.n IS NOT NULL AND mc.n IS NOT NULL THEN 'witnesses' ELSE 'title' END AS basis,
  CASE WHEN pc.n IS NOT NULL AND mc.n IS NOT NULL THEN cast(coalesce(s.n,0) AS DOUBLE)/least(pc.n,mc.n) ELSE coalesce(t.score,0) END AS score
 FROM candidates c
 JOIN package_mods_facts f ON f.package_id=c.package_id
 LEFT JOIN print_counts pc ON pc.package_id=c.package_id
 LEFT JOIN meeting_counts mc ON mc.event_id=c.event_id
 LEFT JOIN shared s ON s.package_id=c.package_id AND s.event_id=c.event_id
 LEFT JOIN titled t ON t.package_id=c.package_id AND t.event_id=c.event_id
), agreeing AS (
 -- Ordered windows (first_value), not unbounded aggregates over the partition (join audit).
 SELECT *,NOT first_value(not_held) OVER(PARTITION BY package_id,day ORDER BY not_held ASC) AS some_sat FROM decided WHERE agrees
), sat AS (
 SELECT *,first_value(score) OVER(PARTITION BY package_id,day ORDER BY score DESC) AS best FROM agreeing WHERE NOT (not_held AND some_sat)
)
-- One print records one meeting a day: of several same-day meetings that agree (a hearing and a markup of
-- the same bills, 100692 and 100693), the best match keeps it; ties stay.
SELECT package_id,event_id,basis,
 CASE WHEN coalesce(cardinality(named_meetings),0)>0 THEN array_has(named_meetings,event_id) END AS named
FROM sat WHERE score=best
