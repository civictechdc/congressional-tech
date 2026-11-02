-- Which meetings each print records (ct-dx22): it was held on the meeting's date and its title agrees
-- with the meeting's, at least half the shorter title's substantive words (3+ characters, not stop words)
-- shared. "U.S. Cyber Diplomacy" shares only letters with "Assessing the U.S.-Qatar Relationship" (106328).
-- named says whether the print states this meeting's eventId; it is null when the print states none.
-- Candidates are only the meetings held on one of the print's days, a small same-day join.
WITH prints AS (
 SELECT package_id,named_meetings,unnest(held_dates) AS day,array_distinct(array_except(string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words FROM package_mods_facts
), meetings AS (
 SELECT event_id,cast(meeting_date AS VARCHAR) AS day,array_distinct(array_except(string_to_array(trim(regexp_replace(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g'),'\b[a-z0-9]{1,2}\b',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words FROM meetings_resolved WHERE meeting_date IS NOT NULL
)
SELECT DISTINCT p.package_id,m.event_id,
 CASE WHEN coalesce(cardinality(p.named_meetings),0)>0 THEN array_has(p.named_meetings,m.event_id) END AS named
FROM prints p JOIN meetings m ON p.day=m.day
WHERE least(cardinality(p.words),cardinality(m.words))>0
 AND 2*cardinality(array_intersect(p.words,m.words))>=least(cardinality(p.words),cardinality(m.words))
