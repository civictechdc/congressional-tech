WITH keys AS (
 SELECT DISTINCT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered WHERE meeting_keys IS NOT NULL
 UNION
 SELECT DISTINCT event_id FROM meetings_resolved WHERE event_id IS NOT NULL
), transcript_rows AS (
 SELECT DISTINCT l.event_id,d.package_id,cast(d.list_row AS INT) AS list_row
 FROM meeting_transcript_links l
 JOIN details d ON l.package_id=d.package_id
 WHERE d.package_id IS NOT NULL
), transcripts_agg AS (
 SELECT event_id,array_agg(named_struct(
  'package_id',package_id,'list_row',list_row
 ) ORDER BY list_row ASC,package_id ASC) AS transcripts
 FROM transcript_rows GROUP BY event_id
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
  'place',cast(NULL AS VARCHAR))),1,0)) AS sittings,
 coalesce(m.committees,array_slice(make_array(named_struct(
  'system_code',cast(NULL AS VARCHAR),'role',cast(NULL AS VARCHAR))),1,0)) AS committees,
 coalesce(m.subject_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS subject_keys,
 coalesce(t.transcripts,array_slice(make_array(named_struct(
  'package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT))),1,0)) AS transcripts,
 coalesce(m.videos,array_slice(make_array(named_struct(
  'name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)) AS videos
FROM keys k
LEFT JOIN meetings_resolved m ON k.event_id=m.event_id
LEFT JOIN transcripts_agg t ON k.event_id=t.event_id
WHERE k.event_id IS NOT NULL
