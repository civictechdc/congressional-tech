WITH keys AS (
 SELECT DISTINCT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered WHERE meeting_keys IS NOT NULL
 UNION
 SELECT DISTINCT event_id FROM meetings_resolved WHERE event_id IS NOT NULL
), own_evidence AS (
 -- What the meeting's own records hold of a sitting: a transcript file its record lists, or witnesses
 -- tied to it alone. 116450 (Rescheduled) lists HHRG-118-VR09-Transcript-20231108.pdf and 14 witnesses.
 SELECT event_id FROM meeting_document_urls WHERE regexp_like(url,'(?i)transcript')
 UNION
 SELECT event_id FROM appearance_records_resolved WHERE event_id IS NOT NULL AND name IS NOT NULL
), reschedule_rows AS (
 -- Postponed/Canceled (not_held) says no sitting on this date. Rescheduled is ambiguous: re-dated in place
 -- (106383, own video) or re-entered (101422, raw MODS shows the twin's print), so the record's own
 -- recording, transcript or witnesses mean it sat. Jackets are not own evidence: Congress.gov lists
 -- same-day jackets of other hearings (101422 lists 87484 "PPACA...", held 2013-10-24). Parts live in
 -- title_key (ct-asdg); a hearing never moves to a markup of the same bills (116450 -> 116562).
 SELECT r.event_id,r.meeting_date,r.title_key,r.reschedule_candidate,r.committee_key,
  coalesce(array_length(r.videos),0)>0 OR e.event_id IS NOT NULL AS sat,
  coalesce(array_length(r.videos),0)>0 AS has_video,
  coalesce(r.not_held,false) AS not_held,
  lower(coalesce(r.status,''))='rescheduled' AS rescheduled,
  CASE WHEN upper(coalesce(r.meeting_type,'')) IN ('HHRG') OR lower(coalesce(r.meeting_type,'')) LIKE '%hearing%' THEN 'hearing'
       WHEN upper(coalesce(r.meeting_type,'')) IN ('HMKP') OR lower(coalesce(r.meeting_type,'')) LIKE '%markup%' THEN 'markup' END AS kind
 FROM meetings_resolved r LEFT JOIN (SELECT DISTINCT event_id FROM own_evidence) e ON r.event_id=e.event_id
 WHERE r.title_key IS NOT NULL AND r.committee_key IS NOT NULL
), twins AS (
 SELECT old.event_id,(old.not_held OR old.rescheduled) AS stated,twin.event_id AS twin_id,twin.meeting_date
 FROM reschedule_rows old JOIN reschedule_rows twin ON old.title_key=twin.title_key AND old.committee_key=twin.committee_key
 WHERE twin.meeting_date>old.meeting_date AND twin.meeting_date<=old.meeting_date+INTERVAL '60' DAY
  AND NOT twin.not_held
  AND (old.kind IS NULL OR twin.kind IS NULL OR old.kind=twin.kind)
  AND (old.not_held OR (NOT old.sat AND (old.rescheduled OR (old.reschedule_candidate AND twin.has_video))))
), first_twin AS (
 SELECT *,row_number() OVER(PARTITION BY event_id ORDER BY meeting_date,twin_id) AS rn FROM twins
), rescheduled AS (
 SELECT event_id,twin_id AS rescheduled_to,CASE WHEN stated THEN 'publisher_status' ELSE 'recording_on_later_twin' END AS rescheduled_basis FROM first_twin WHERE rn=1
), transcript_rows AS (
 SELECT DISTINCT l.event_id,d.package_id,cast(d.list_row AS INT) AS list_row,d.format
 FROM meeting_transcript_links l
 JOIN details d ON l.package_id=d.package_id
 WHERE d.package_id IS NOT NULL
), transcript_preferred AS (
 -- One entry per (meeting, package): the package's document whose saved format ranks first.
 SELECT r.event_id,r.package_id,r.list_row,row_number() OVER (
  PARTITION BY r.event_id,r.package_id ORDER BY coalesce(p.rank,2147483647),r.list_row) AS rn
 FROM formats p RIGHT JOIN transcript_rows r ON p.kind='preference' AND p.value=r.format
), transcript_row_formats AS (
 SELECT list_row,format FROM transcript_rows
 UNION SELECT cast(a.row_id AS INT) AS list_row,a.alt['format'] AS format FROM (
  SELECT d.list_row AS row_id,unnest(d.alternates) AS alt FROM details d
  WHERE d.package_id IS NOT NULL AND coalesce(array_length(d.alternates),0)>0) a
), transcript_formats AS (
 SELECT f.event_id,f.package_id,array_agg(f.format ORDER BY coalesce(p.rank,2147483647),f.format) AS formats
 FROM formats p RIGHT JOIN (
  SELECT DISTINCT r.event_id,r.package_id,x.format FROM transcript_rows r
  JOIN transcript_row_formats x ON x.list_row=r.list_row WHERE x.format IS NOT NULL
 ) f ON p.kind='preference' AND p.value=f.format
 GROUP BY f.event_id,f.package_id
), transcript_ranked AS (
 SELECT t.event_id,t.package_id,t.list_row,f.formats,row_number() OVER (
  PARTITION BY t.event_id
  ORDER BY t.list_row ASC,t.package_id ASC
 ) AS tr_seq
 FROM transcript_preferred t JOIN transcript_formats f ON f.event_id=t.event_id AND f.package_id=t.package_id
 WHERE t.rn=1
), transcripts_agg AS (
 SELECT event_id,array_agg(named_struct(
  'package_id',package_id,'list_row',list_row,'formats',formats
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
  'package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT),
  'formats',arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'))),1,0)) AS transcripts,
 coalesce(m.videos,array_slice(make_array(named_struct(
  'name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)) AS videos,
 cast(m.congress AS SMALLINT) AS congress,
 m.congress_gov_updated,
 m.house_xml_updated,
 m.congress_gov_meeting_type,
 m.access,
 m.access_basis,
 m.not_held,
 r.rescheduled_to,
 r.rescheduled_basis
FROM keys k
LEFT JOIN meetings_resolved m ON k.event_id=m.event_id
LEFT JOIN transcripts_agg t ON k.event_id=t.event_id
LEFT JOIN rescheduled r ON k.event_id=r.event_id
WHERE k.event_id IS NOT NULL
