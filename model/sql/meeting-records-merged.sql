WITH event_keys AS (
 SELECT DISTINCT event_id FROM meeting_records_current
), merged AS (
 SELECT k.event_id,
  coalesce(h.chamber,c.chamber) AS chamber,
  coalesce(h.congress,c.congress) AS congress,
  coalesce(h.session,c.session) AS session,
  coalesce(h.updated,c.updated) AS updated,
  c.updated AS congress_gov_updated,
  h.updated_literal AS house_xml_updated,
  c.meeting_type AS congress_gov_meeting_type,
  coalesce(h.title,c.title) AS title,
  coalesce(h.meeting_date,c.meeting_date) AS meeting_date,
  coalesce(h.meeting_type,c.meeting_type) AS meeting_type,
  coalesce(h.status,c.status) AS status,
  -- Congress.gov states instants and places; House XML states unzoned Eastern
  -- local times and, today, no parsed place. So Congress.gov leads for sittings,
  -- while an explicit empty or unrecognized House state still blocks any fallback.
  CASE WHEN h.sittings_state IN ('empty','unrecognized') THEN NULL
       WHEN c.sittings_state='present' THEN c.sittings
       WHEN h.sittings_state='present' THEN h.sittings END AS raw_sittings,
  coalesce(h.sittings_state='present' AND coalesce(c.sittings_state,'')<>'present',false) AS sittings_are_eastern,
  CASE WHEN h.committees_state='present' THEN h.committees
       WHEN h.committees_state IN ('empty','unrecognized') THEN NULL
       WHEN c.committees_state='present' THEN c.committees END AS raw_committees,
  h.subject_keys AS house_subjects,
  c.subject_keys AS congress_subjects,
  CASE WHEN h.jackets_state='present' THEN h.transcript_jackets
       WHEN h.jackets_state IN ('empty','unrecognized') THEN NULL
       WHEN c.jackets_state='present' THEN c.transcript_jackets END AS raw_jackets,
  CASE WHEN h.videos_state='present' THEN h.videos
       WHEN h.videos_state IN ('empty','unrecognized') THEN NULL
       WHEN c.videos_state='present' THEN c.videos END AS raw_videos
 FROM event_keys k
 LEFT JOIN meeting_records_current h ON k.event_id=h.event_id AND h.source='house_xml'
 LEFT JOIN meeting_records_current c ON k.event_id=c.event_id AND c.source='congress_gov'
)
SELECT * FROM merged
