-- A package whose own MODS names a meeting links to it, as a jacket listed by the meeting does, but only
-- where the print records that meeting (held that day under an agreeing title): GPO's eventId alone is
-- sometimes another same-day hearing's or the wrong event's.
SELECT DISTINCT a.package_id,m.event_id,m.meeting_date,m.chamber
FROM print_meeting_agreement a
JOIN meetings_resolved m ON m.event_id=a.event_id
WHERE a.named
