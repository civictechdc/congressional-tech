-- A printed hearing can be refiled as an attachment to a different meeting.
-- Correct a later filename date only when the package records an earlier held
-- meeting under an agreeing title or witness list (package_meeting_links).
-- Keep filename dates that match any day in a multi-day print. Use an unknown
-- date when a reposting has several possible dates in the print.
WITH print_sittings AS (
 SELECT l.package_id,
  min(m.meeting_date) AS first_day,max(m.meeting_date) AS last_day
 FROM package_meeting_links l
 JOIN meetings_resolved m ON m.event_id=l.event_id
 WHERE NOT coalesce(m.not_held,false)
 GROUP BY l.package_id
), checked AS (
 SELECT n.doc_key,
  CASE WHEN s.first_day=s.last_day AND array_length(f.held_dates)=1 THEN s.first_day END AS hearing_date
 FROM print_sittings s JOIN package_mods_facts f ON f.package_id=s.package_id
 JOIN base_normalized n ON n.package_id=s.package_id
 WHERE n.document_date_source='filename' AND n.document_date>s.last_day
  AND regexp_like(n.package_id,'(?i)^CHRG-[0-9]+[hsj]hrg[0-9]+$')
  AND NOT coalesce(array_has(f.held_dates,cast(n.document_date AS VARCHAR)),false)
)
SELECT doc_key,hearing_date AS document_date,
 CASE WHEN hearing_date IS NOT NULL THEN 'meeting' END AS document_date_source
FROM checked
