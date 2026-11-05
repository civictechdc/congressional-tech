WITH keys AS (
 SELECT DISTINCT try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered WHERE meeting_keys IS NOT NULL
 UNION
 SELECT DISTINCT event_id FROM meetings_resolved WHERE event_id IS NOT NULL
), printed AS (
 -- A print held on the meeting's date under its title (package_meeting_links) shows the meeting sat,
 -- whatever its status: Congress.gov states Canceled for 101498, 101400, 104460 and 101644, whose own
 -- prints record the hearing that day. The publisher status stays, so the conflict remains visible.
 SELECT DISTINCT event_id FROM package_meeting_links
), own_evidence AS (
 -- What the meeting's own records hold of a sitting: its print, a transcript file its record lists, or
 -- its own witness list (House XML or Congress.gov). Witnesses attached from a package are not its own:
 -- 101422 carried 87484's PPACA witnesses. 116450 (Rescheduled) lists HHRG-118-VR09-Transcript-20231108.pdf.
 SELECT event_id FROM printed
 UNION
 SELECT event_id FROM meeting_document_urls WHERE regexp_like(url,'(?i)transcript')
 UNION
 SELECT event_id FROM appearance_records_resolved
 WHERE event_id IS NOT NULL AND name IS NOT NULL AND source IN ('house_xml','congress_gov')
), reschedule_rows AS (
 -- Postponed/Canceled (not_held) says no sitting on this date. Rescheduled is ambiguous: re-dated in place
 -- (106383, own video) or re-entered (101422, raw MODS shows the twin's print), so the record's own
 -- recording, transcript or witnesses mean it sat. Jackets are not own evidence: Congress.gov lists
 -- same-day jackets of other hearings (101422 lists 87484 "PPACA...", held 2013-10-24). Parts live in
 -- title_key (ct-asdg); a hearing never moves to a markup of the same bills (116450 -> 116562).
 SELECT r.event_id,r.meeting_date,r.title_key,r.reschedule_candidate,r.committee_key,
  coalesce(array_length(r.videos),0)>0 OR e.event_id IS NOT NULL AS sat,
  coalesce(array_length(r.videos),0)>0 AS has_video,
  coalesce(r.not_held,false) AND pr.event_id IS NULL AS not_held,
  lower(coalesce(r.status,''))='rescheduled' AS rescheduled,
  CASE WHEN upper(coalesce(r.meeting_type,'')) IN ('HHRG') OR lower(coalesce(r.meeting_type,'')) LIKE '%hearing%' THEN 'hearing'
       WHEN upper(coalesce(r.meeting_type,'')) IN ('HMKP') OR lower(coalesce(r.meeting_type,'')) LIKE '%markup%' THEN 'markup' END AS kind
 FROM meetings_resolved r LEFT JOIN (SELECT DISTINCT event_id FROM own_evidence) e ON r.event_id=e.event_id
 LEFT JOIN printed pr ON r.event_id=pr.event_id
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
), transcript_links AS (
 -- Use vetted print links when MODS facts are available. Congress.gov lists 52109 on 330128,
 -- another hearing's print. Without MODS facts the jacket link stands.
 SELECT package_id,event_id FROM package_meeting_links
 UNION
 SELECT l.package_id,l.event_id FROM meeting_transcript_links l
 LEFT JOIN package_mods_facts f ON f.package_id=l.package_id WHERE f.package_id IS NULL
), recording_tracks AS (
 SELECT video_key,event_ids,t['format'] AS format,t['language'] AS language,t['production'] AS production,t['body'] AS body
 FROM (SELECT video_key,event_ids,unnest(tracks) AS t FROM recordings_entity WHERE tracks IS NOT NULL)
), caption_tracks AS (
 SELECT DISTINCT video_key,unnest(event_ids) AS event_id,format,language,production FROM recording_tracks
 -- The empty body's digest is no caption file (338611's YouTube track is 0 bytes).
 WHERE format IN ('vtt','srt','ttml') AND body IS NOT NULL AND event_ids IS NOT NULL
  AND body<>arrow_cast(decode('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','hex'),'FixedSizeBinary(32)')
), transcript_rows AS (
 SELECT DISTINCT l.event_id,d.package_id,cast(d.list_row AS INT) AS list_row,d.format
 FROM transcript_links l
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
), transcript_sources AS (
 SELECT t.event_id,'printed_hearing' AS source,t.package_id,t.list_row,f.formats,
  cast(NULL AS VARCHAR) AS video_key,cast(NULL AS VARCHAR) AS language,cast(NULL AS VARCHAR) AS production
 FROM transcript_preferred t JOIN transcript_formats f ON f.event_id=t.event_id AND f.package_id=t.package_id
 WHERE t.rn=1
 UNION ALL
 -- A committee's own transcript (ct-1i4q): a held file the meeting's current record lists (by name) whose
 -- name is the House transcript form, H{HRG,MKP,MTG}-<congress>-<committee>-Transcript-<yyyymmdd>[-<part>].pdf,
 -- dated the meeting's day (HHRG-118-VR09-Transcript-20231108.pdf). Every listed transcript file on v21 has
 -- this form; a file linked only by its folder path is not one the record lists.
 SELECT DISTINCT m.event_id,'committee_transcript' AS source,cast(NULL AS VARCHAR) AS package_id,cast(o.list_row AS INT) AS list_row,
  arrow_cast(array_slice(make_array(o.format),1,CASE WHEN o.format IS NULL THEN 0 ELSE 1 END),'List(Utf8)') AS formats,
  cast(NULL AS VARCHAR) AS video_key,cast(NULL AS VARCHAR) AS language,cast(NULL AS VARCHAR) AS production
 FROM (SELECT list_row,filename,format,try_cast(unnest(meeting_keys) AS BIGINT) AS event_id FROM ordered
  WHERE regexp_like(filename,'(?i)^H(?:HRG|MKP|MTG)-[0-9]{3}-[A-Z]{2}[0-9]{2}-Transcript-[0-9]{8}(?:-[A-Z0-9]+)?[.]pdf$')) o
 JOIN meetings_resolved m ON m.event_id=o.event_id
  AND (regexp_match(o.filename,'(?i)-Transcript-([0-9]{8})'))[1]=replace(cast(m.meeting_date AS VARCHAR),'-','')
 JOIN (SELECT DISTINCT event_id,lower(regexp_replace(url,'^.*/','')) AS name FROM meeting_document_urls) d
  ON d.event_id=o.event_id AND d.name=lower(o.filename)
 UNION ALL
 -- Captions and subtitles (ct-1i4q): complete caption files of the meeting's recordings. A vtt beside a
 -- playlist of the same production is one segment of that stream, not a track (ct-9s7b), and a track
 -- with no body is not held.
 SELECT DISTINCT c.event_id,'captions' AS source,cast(NULL AS VARCHAR) AS package_id,cast(NULL AS INT) AS list_row,
  arrow_cast(make_array(c.format),'List(Utf8)') AS formats,c.video_key,c.language,c.production
 FROM caption_tracks c
 LEFT JOIN (SELECT DISTINCT video_key,production FROM recording_tracks WHERE format='m3u8') p
  ON p.video_key=c.video_key AND p.production IS NOT DISTINCT FROM c.production
 WHERE p.video_key IS NULL
), transcript_ranked AS (
 SELECT *,row_number() OVER (
  PARTITION BY event_id
  ORDER BY CASE source WHEN 'printed_hearing' THEN 0 WHEN 'committee_transcript' THEN 1 ELSE 2 END,
   list_row ASC NULLS LAST,package_id ASC NULLS LAST,video_key ASC NULLS LAST,language ASC NULLS LAST,production ASC NULLS LAST
 ) AS tr_seq
 FROM transcript_sources
), transcripts_agg AS (
 SELECT event_id,array_agg(named_struct(
  'source',source,'package_id',package_id,'list_row',list_row,'formats',formats,
  'video_key',video_key,'language',language,'production',production
 ) ORDER BY tr_seq ASC) AS transcripts
 FROM transcript_ranked GROUP BY event_id
), nomination_hearing_chunks AS (
 SELECT
  cast(congress AS VARCHAR)||'-pn-'||cast(number AS VARCHAR)||
  CASE
   WHEN part_number IS NOT NULL AND try_cast(part_number AS INT) IS NOT NULL AND try_cast(part_number AS INT)<>0
    THEN '-'||regexp_replace(trim(part_number),'^0+','')
   ELSE ''
  END AS nomination_id,
  congress,
  unnest(string_to_array(hearings_json,'}')) AS chunk
 FROM spicy_nominations
 WHERE congress IS NOT NULL AND number IS NOT NULL AND hearings_json IS NOT NULL
), nomination_hearing_packages AS (
 SELECT DISTINCT nomination_id,
  coalesce(
   (regexp_match(chunk,'(?i)"package_?id"\s*:\s*"([^"]+)"'))[1],
   (regexp_match(chunk,'(CHRG-[0-9]+[hsj]hrg[0-9]+)'))[1],
   CASE WHEN regexp_like(chunk,'(?i)"jacket(?:_?number)?"\s*:\s*"?([0-9]+)"?')
    THEN 'CHRG-'||cast(congress AS VARCHAR)||
     (CASE lower(coalesce((regexp_match(chunk,'(?i)"chamber"\s*:\s*"([^"]+)"'))[1],'senate'))
      WHEN 'house' THEN 'h' WHEN 'joint' THEN 'j' ELSE 's' END)||'hrg'||
     (regexp_match(chunk,'(?i)"jacket(?:_?number)?"\s*:\s*"?([0-9]+)"?'))[1]
   END
  ) AS package_id
 FROM nomination_hearing_chunks
), combined_subjects AS (
 SELECT event_id,nullif(lower(trim(unnest(subject_keys))),'') AS subject_key
 FROM meetings_resolved
 WHERE subject_keys IS NOT NULL
 UNION
 SELECT try_cast(o.meeting_keys[1] AS BIGINT) AS event_id,
  nullif(lower(trim(unnest(o.measure_keys))),'') AS subject_key
 FROM ordered o
 WHERE coalesce(array_length(o.meeting_keys),0)=1
   AND o.measure_keys IS NOT NULL
 UNION
 SELECT tr.event_id,lower(trim(np.nomination_id)) AS subject_key
 FROM transcript_ranked tr
 JOIN nomination_hearing_packages np ON np.package_id=tr.package_id
 WHERE tr.package_id IS NOT NULL AND np.package_id IS NOT NULL
), subject_keys_by_event AS (
 SELECT event_id,array_agg(subject_key ORDER BY subject_key) AS subject_keys
 FROM (
  SELECT DISTINCT event_id,subject_key
  FROM combined_subjects
  WHERE event_id IS NOT NULL AND subject_key IS NOT NULL AND subject_key<>''
 )
 GROUP BY event_id
)
SELECT k.event_id,
 m.chamber,
 CASE
  WHEN m.event_id IS NULL THEN 'meeting_detail_missing'
  WHEN m.chamber IS NULL THEN 'source_chamber_unknown'
  ELSE 'source'
 END AS chamber_basis,
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
 coalesce(sk.subject_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS subject_keys,
 coalesce(t.transcripts,array_slice(make_array(named_struct(
  'source',cast(NULL AS VARCHAR),'package_id',cast(NULL AS VARCHAR),'list_row',cast(NULL AS INT),
  'formats',arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)'),
  'video_key',cast(NULL AS VARCHAR),'language',cast(NULL AS VARCHAR),'production',cast(NULL AS VARCHAR))),1,0)) AS transcripts,
 coalesce(m.videos,array_slice(make_array(named_struct(
  'name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)) AS videos,
 cast(m.congress AS SMALLINT) AS congress,
 m.congress_gov_updated,
 m.house_xml_updated,
 m.congress_gov_meeting_type,
 m.access,
 m.access_basis,
 m.not_held AND pr.event_id IS NULL AS not_held,
 r.rescheduled_to,
 r.rescheduled_basis,
 m.document_references
FROM keys k
LEFT JOIN meetings_resolved m ON k.event_id=m.event_id
LEFT JOIN subject_keys_by_event sk ON k.event_id=sk.event_id
LEFT JOIN transcripts_agg t ON k.event_id=t.event_id
LEFT JOIN rescheduled r ON k.event_id=r.event_id
LEFT JOIN printed pr ON k.event_id=pr.event_id
WHERE k.event_id IS NOT NULL
