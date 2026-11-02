-- A package's witnesses, video and print stand for a meeting only when its own MODS records that meeting
-- (print_meeting_agreement: held that day under an agreeing title) and, if it names meetings by <eventId>,
-- it names this one. A jacket list or an eventId alone cannot decide: GPO puts one eventId on several
-- same-day hearings or on the wrong event (330128, 326063), and Congress.gov lists same-day jackets of
-- other hearings. A multi-day print stands for each day's meeting it names; every agreeing print counts.
SELECT DISTINCT l.package_id,l.event_id
FROM meeting_transcript_links l
JOIN print_meeting_agreement a ON a.package_id=l.package_id AND a.event_id=l.event_id
WHERE a.named IS NULL OR a.named
