-- A package's witnesses, video and print stand for a meeting only when its own print records that meeting
-- (print_meeting_agreement: held that day, the same witnesses or, without lists, an agreeing title). A jacket
-- list or a GovInfo eventId alone cannot decide: GPO puts one eventId on several same-day hearings or on the
-- wrong event (330128, 326063), and Congress.gov lists same-day jackets of other hearings (330128 -> 52109).
-- A multi-day print stands for each day's meeting; every agreeing print counts.
SELECT DISTINCT l.package_id,l.event_id
FROM meeting_transcript_links l
JOIN print_meeting_agreement a ON a.package_id=l.package_id AND a.event_id=l.event_id
