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
  -- Congress.gov leads, as for sittings; House XML (S/R/P, read from the root) fills House-only events.
  coalesce(c.status,h.status) AS status,
  -- The first source stating access decides; unknown states nothing.
  coalesce(nullif(c.access,'unknown'),nullif(h.access,'unknown'),c.access,h.access) AS access,
  CASE WHEN nullif(c.access,'unknown') IS NOT NULL THEN concat('congress_gov',c.access_basis)
       WHEN nullif(h.access,'unknown') IS NOT NULL THEN concat('house_xml',h.access_basis) END AS access_basis,
  -- A curated read found the meeting's own recording of it on its date: held, whatever the status says.
  (coalesce(c.not_held,false) OR coalesce(h.not_held,false)) AND sc.event_id IS NULL AS not_held,
  coalesce(c.title_key,h.title_key) AS title_key,
  coalesce(c.reschedule_candidate,h.reschedule_candidate) AS reschedule_candidate,
  -- Congress.gov leads for sittings and House XML fills what it lacks, because each states
  -- facts the other omits. An explicit empty or unrecognized House state still blocks fallback.
  CASE WHEN h.sittings_state IN ('empty','unrecognized') THEN NULL
       WHEN c.sittings_state='present' THEN c.sittings
       WHEN h.sittings_state='present' THEN h.sittings END AS raw_sittings,
  CASE WHEN h.sittings_state='present' THEN h.sittings[1] END AS house_sitting,
  CASE WHEN h.committees_state='present' THEN h.committees
       WHEN h.committees_state IN ('empty','unrecognized') THEN NULL
       WHEN c.committees_state='present' THEN c.committees END AS raw_committees,
  h.subject_keys AS house_subjects,
  c.subject_keys AS congress_subjects,
  c.document_references,
  CASE WHEN h.jackets_state='present' THEN h.transcript_jackets
       WHEN h.jackets_state IN ('empty','unrecognized') THEN NULL
       WHEN c.jackets_state='present' THEN c.transcript_jackets END AS raw_jackets,
  CASE WHEN h.videos_state='present' THEN h.videos
       WHEN h.videos_state IN ('empty','unrecognized') THEN NULL
       WHEN c.videos_state='present' THEN c.videos END AS raw_videos
 FROM event_keys k
 LEFT JOIN meeting_records_current h ON k.event_id=h.event_id AND h.source='house_xml'
 LEFT JOIN meeting_records_current c ON k.event_id=c.event_id AND c.source='congress_gov'
 LEFT JOIN meeting_status_conflicts sc ON k.event_id=sc.event_id
)
SELECT * FROM merged
