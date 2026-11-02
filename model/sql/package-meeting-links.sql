-- A package's witnesses, video and print stand for a meeting only when its own MODS says so (ct-dx22):
-- the print was held on the meeting's date, its title agrees with the meeting's, and, if it names
-- meetings by <eventId>, it names this one. A jacket list or an eventId alone cannot decide: GPO puts
-- one eventId on several same-day hearings or on the wrong event (330128, 326063), and Congress.gov
-- lists same-day jackets of other hearings. A multi-day print stands for each day's meeting it names.
WITH facts AS (
 SELECT package_id,named_meetings,held_dates,array_distinct(array_except(string_to_array(trim(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words FROM package_mods_facts
), meetings AS (
 SELECT event_id,cast(meeting_date AS VARCHAR) AS day,array_distinct(array_except(string_to_array(trim(regexp_replace(lower(coalesce(title,'')),'[^a-z0-9]+',' ','g')),' '),make_array('','the','a','an','of','and','to','in','on','for','with','from','at','by','is','are','be','as','or','its','it','this','that','hearing','hearings','subcommittee','committee','house','us','part','examining','examine','review','oversight','markup','meeting','full'))) AS words FROM meetings_resolved
)
SELECT DISTINCT l.package_id,l.event_id
FROM meeting_transcript_links l
JOIN facts f ON f.package_id=l.package_id
JOIN meetings m ON m.event_id=l.event_id
WHERE array_has(f.held_dates,m.day)
 AND (coalesce(cardinality(f.named_meetings),0)=0 OR array_has(f.named_meetings,l.event_id))
 -- Titles agree when at least half the shorter title's substantive words are shared.
 AND least(cardinality(f.words),cardinality(m.words))>0
 AND 2*cardinality(array_intersect(f.words,m.words))>=least(cardinality(f.words),cardinality(m.words))
