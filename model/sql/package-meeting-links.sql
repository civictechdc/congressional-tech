-- A package's witnesses or video stand for a meeting only when a raw record justifies that meeting
-- (ct-dx22): the package's own MODS names exactly it, or names none and the link is one-to-one both
-- ways. A jacket list alone cannot decide: Congress.gov lists same-day jackets of other hearings, and
-- one meeting can have several packages. Several packages whose MODS each name the meeting (a print
-- and its errata, volumes) all stand for it.
WITH package_events AS (
 SELECT package_id,count(DISTINCT event_id) AS n FROM meeting_transcript_links GROUP BY package_id
), event_packages AS (
 SELECT event_id,count(DISTINCT package_id) AS n FROM meeting_transcript_links GROUP BY event_id
)
SELECT DISTINCT l.package_id,l.event_id
FROM meeting_transcript_links l
JOIN package_events pe ON pe.package_id=l.package_id
JOIN event_packages ep ON ep.event_id=l.event_id
LEFT JOIN package_mods_facts f ON f.package_id=l.package_id
WHERE CASE WHEN coalesce(array_length(f.named_meetings),0)>0
 THEN array_length(f.named_meetings)=1 AND f.named_meetings[1]=l.event_id
 ELSE pe.n=1 AND ep.n=1 END
