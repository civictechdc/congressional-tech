-- Which meetings each print records (ct-dx22), among the meetings held on one of its days:
-- 1. When both sides list witnesses, the people decide: at least half of the shorter list is the same
--    person (family name, first initial or a nickname, one-letter spelling slips in names of 5+ letters).
--    A GovInfo <eventId> never vetoes (it is wrong on 29369's print) and titles are not consulted
--    ("PENDING LEGISLATION"; boilerplate Armed Services titles fit many hearings).
-- 2. Otherwise the title decides: half the shorter title's substantive words (3+ characters, not stop
--    words) shared. "U.S. Cyber Diplomacy" shares only letters with "Assessing the U.S.-Qatar Relationship".
-- When a print agrees with several same-day meetings, a meeting that did not sit (a superseded duplicate
-- such as 105066, re-entered as 105084) yields to one that did.
-- named records whether the print states this meeting's eventId (null when it states none).
WITH prints AS (
 SELECT package_id,named_meetings,unnest(held_dates) AS day,array_distinct(array_except(string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words FROM package_mods_facts
), meetings AS (
 SELECT event_id,cast(meeting_date AS VARCHAR) AS day,coalesce(not_held,false) AS not_held,array_distinct(array_except(string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words
 FROM meetings_resolved WHERE meeting_date IS NOT NULL
), candidates AS (
 SELECT DISTINCT p.package_id,m.event_id,m.not_held,p.named_meetings,p.words AS print_words,m.words AS meeting_words
 FROM prints p JOIN meetings m ON p.day=m.day
), print_people AS (
 SELECT DISTINCT package_id,family,initial FROM appearance_people
 WHERE source='mods' AND NOT statement AND family IS NOT NULL AND package_id IS NOT NULL
), meeting_people AS (
 SELECT DISTINCT event_id,family,initial FROM appearance_people
 WHERE source IN ('house_xml','congress_gov') AND NOT statement AND family IS NOT NULL AND event_id IS NOT NULL
), print_counts AS (SELECT package_id,count(*) AS n FROM print_people GROUP BY package_id
), meeting_counts AS (SELECT event_id,count(*) AS n FROM meeting_people GROUP BY event_id
), shared AS (
 SELECT c.package_id,c.event_id,count(DISTINCT concat(a.family,'|',coalesce(a.initial,''))) AS n
 FROM candidates c
 JOIN print_people a ON a.package_id=c.package_id
 JOIN meeting_people b ON b.event_id=c.event_id
 WHERE (a.family=b.family OR (length(a.family)>=5 AND levenshtein(a.family,b.family)<=1))
  AND (a.initial IS NULL OR b.initial IS NULL OR a.initial=b.initial
   -- Nicknames: Bob/Bill/Dick for Robert/William/Richard, Ted/Ned/Liz/Betsy for Edward/Elizabeth, Peggy.
   OR concat(least(a.initial,b.initial),greatest(a.initial,b.initial)) IN ('br','bw','dr','et','en','el','be','mp'))
 GROUP BY c.package_id,c.event_id
), decided AS (
 SELECT c.package_id,c.event_id,c.not_held,c.named_meetings,
  CASE WHEN pc.n IS NOT NULL AND mc.n IS NOT NULL THEN 2*coalesce(s.n,0)>=least(pc.n,mc.n)
   ELSE least(cardinality(c.print_words),cardinality(c.meeting_words))>0
    AND 2*cardinality(array_intersect(c.print_words,c.meeting_words))>=least(cardinality(c.print_words),cardinality(c.meeting_words))
  END AS agrees,
  CASE WHEN pc.n IS NOT NULL AND mc.n IS NOT NULL THEN 'witnesses' ELSE 'title' END AS basis
 FROM candidates c
 LEFT JOIN print_counts pc ON pc.package_id=c.package_id
 LEFT JOIN meeting_counts mc ON mc.event_id=c.event_id
 LEFT JOIN shared s ON s.package_id=c.package_id AND s.event_id=c.event_id
), agreeing AS (
 SELECT *,bool_or(NOT not_held) OVER(PARTITION BY package_id) AS some_sat FROM decided WHERE agrees
)
SELECT package_id,event_id,basis,
 CASE WHEN coalesce(cardinality(named_meetings),0)>0 THEN array_has(named_meetings,event_id) END AS named
FROM agreeing
WHERE NOT (not_held AND some_sat)
