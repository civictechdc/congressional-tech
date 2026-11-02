WITH keys AS (
 SELECT DISTINCT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered WHERE meeting_keys IS NOT NULL
 UNION
 SELECT DISTINCT event_id FROM meetings_resolved WHERE event_id IS NOT NULL
), reschedule_evidence AS (
 -- A postponed meeting re-entered under a new event ID keeps its old record as scheduled.
 SELECT event_id,meeting_date,title_key,reschedule_candidate,
  committee_key,
  coalesce(array_length(videos),0)>0 OR coalesce(array_length(transcript_jackets),0)>0 AS has_evidence
 FROM meetings_resolved
 WHERE title_key IS NOT NULL AND committee_key IS NOT NULL
), rescheduled AS (
 SELECT o.event_id,min(n.event_id) AS rescheduled_to FROM (
  SELECT old.event_id,min(twin.meeting_date) AS first_date,old.title_key,old.committee_key
  FROM reschedule_evidence old JOIN reschedule_evidence twin ON old.title_key=twin.title_key AND old.committee_key=twin.committee_key
  WHERE NOT old.has_evidence AND old.reschedule_candidate AND twin.has_evidence
   AND twin.meeting_date>old.meeting_date AND twin.meeting_date<=old.meeting_date+INTERVAL '60' DAY
  GROUP BY old.event_id,old.title_key,old.committee_key
 ) o JOIN reschedule_evidence n ON n.title_key=o.title_key AND n.committee_key=o.committee_key AND n.meeting_date=o.first_date AND n.has_evidence
 GROUP BY o.event_id
), transcript_rows AS (
 SELECT DISTINCT l.event_id,d.package_id,cast(d.list_row AS INT) AS list_row
 FROM meeting_transcript_links l
 JOIN details d ON l.package_id=d.package_id
 WHERE d.package_id IS NOT NULL
), transcript_ranked AS (
 SELECT *,row_number() OVER (
  PARTITION BY event_id
  ORDER BY list_row ASC,package_id ASC
 ) AS tr_seq
 FROM transcript_rows
), transcripts_agg AS (
 SELECT event_id,array_agg(named_struct(
  'package_id',package_id,'list_row',list_row
 ) ORDER BY tr_seq ASC) AS transcripts
 FROM transcript_ranked GROUP BY event_id
)
SELECT k.event_id,
 m.chamber,
 m.title,
 m.meeting_date,
 m.meeting_type,
 m.session,
 m.status,
 coalesce(m.sittings,array_slice(make_array(named_struct(
  'start',arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))'),
  'end',arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))'),
  'place',cast(NULL AS VARCHAR),'room',cast(NULL AS VARCHAR),'building',cast(NULL AS VARCHAR),'address',cast(NULL AS VARCHAR))),1,0)) AS sittings,
 coalesce(m.committees,array_slice(make_array(named_struct(
  'system_code',cast(NULL AS VARCHAR),'role',cast(NULL AS VARCHAR))),1,0)) AS committees,
 coalesce(m.subject_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS subject_keys,
 coalesce(t.transcripts,array_slice(make_array(named_struct(
  'package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT))),1,0)) AS transcripts,
 coalesce(m.videos,array_slice(make_array(named_struct(
  'name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)) AS videos,
 cast(m.congress AS SMALLINT) AS congress,
 m.congress_gov_updated,
 m.house_xml_updated,
 m.congress_gov_meeting_type,
 m.access,
 m.access_basis,
 m.not_held,
 r.rescheduled_to
FROM keys k
LEFT JOIN meetings_resolved m ON k.event_id=m.event_id
LEFT JOIN transcripts_agg t ON k.event_id=t.event_id
LEFT JOIN rescheduled r ON k.event_id=r.event_id
WHERE k.event_id IS NOT NULL
