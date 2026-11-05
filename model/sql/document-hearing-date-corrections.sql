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
UNION ALL
SELECT n.doc_key,
 CASE WHEN array_has(f.held_dates,v.cover_day) AND (v.event_id IS NULL OR m.event_id IS NOT NULL)
  THEN cast(v.cover_day AS DATE) END AS document_date,
 CASE WHEN array_has(f.held_dates,v.cover_day) AND (v.event_id IS NULL OR m.event_id IS NOT NULL)
  THEN CASE WHEN v.event_id IS NULL THEN 'content' ELSE 'meeting' END END AS document_date_source
-- ct-cxc5: independently checked GovInfo covers. Bind the evidence to the printed bytes.
-- The September print also has a vetted September event. The other attachments establish
-- the dates of their own events and remain linked, even though the print covers differ.
FROM (VALUES
 ('CHRG-112hhrg68347','09bd414d3340e2460f48c6894ebdea0d3ee2420456ec1fde19a2e8f75f59a81f','2011-09-22',cast(103921 AS BIGINT)),
 ('CHRG-112hhrg80849','a600af79338071e29eba24fcb61977e89635fc0e6c1de7948013cddb3fe95749','2012-06-25',cast(NULL AS BIGINT)),
 ('CHRG-113hhrg82590','dc3e89f2578626fda386ab7fc85ae735dbeee8b69d6b2801b504b7ba7a88bc56','2013-05-09',cast(NULL AS BIGINT))
) v(package_id,body_hex,cover_day,event_id)
JOIN base_normalized n ON n.package_id=v.package_id AND n.body_hex=v.body_hex
LEFT JOIN package_mods_facts f ON f.package_id=v.package_id
LEFT JOIN package_meeting_links l ON l.package_id=v.package_id AND l.event_id=v.event_id
LEFT JOIN meetings_resolved m ON m.event_id=l.event_id AND m.meeting_date=cast(v.cover_day AS DATE)
 AND NOT coalesce(m.not_held,false)
WHERE n.document_date_source='meeting' AND n.document_date<>cast(v.cover_day AS DATE)
