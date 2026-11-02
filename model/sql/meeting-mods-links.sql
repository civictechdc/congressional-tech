-- A package whose own MODS names a meeting links to it, as a jacket listed by the meeting does.
SELECT DISTINCT f.package_id,m.event_id,m.meeting_date,m.chamber
FROM (SELECT package_id,unnest(named_meetings) AS event_id FROM package_mods_facts) f
JOIN meetings_resolved m ON m.event_id=f.event_id
WHERE f.event_id IS NOT NULL
