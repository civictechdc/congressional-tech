WITH selected_meeting_records AS (
 SELECT r.*
 FROM meeting_records_input r
 WHERE (
  NOT EXISTS (SELECT 1 FROM parser_versions WHERE parser LIKE 'meeting_records.%')
  OR EXISTS (
   SELECT 1 FROM parser_versions v
   WHERE v.parser='meeting_records.'||r.source AND v.version=r.parser_version
  )
 )
), candidate_meeting_shas AS (
 SELECT DISTINCT record_sha_hex
 FROM selected_meeting_records
 WHERE record_sha_hex IS NOT NULL
), fetch_times AS (
 SELECT encode(c.sha256,'hex') AS record_sha_hex,
  max(arrow_cast(cast(c.retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS retrieved_at
 FROM captures c
 JOIN candidate_meeting_shas cms ON encode(c.sha256,'hex')=cms.record_sha_hex
 WHERE c.sha256 IS NOT NULL AND c.mode='fetch' AND c.complete AND c.outcome IN ('stored','unchanged') AND c.http_status BETWEEN 200 AND 299
 GROUP BY c.sha256
), expanded AS (
 SELECT r.record_sha_hex,r.source,ms.priority,f.retrieved_at,unnest(r.meetings) AS m
 FROM selected_meeting_records r
 JOIN meeting_sources ms ON ms.kind='meeting' AND r.source=ms.source
 LEFT JOIN fetch_times f ON r.record_sha_hex=f.record_sha_hex
 WHERE r.status='completed' AND r.meetings IS NOT NULL
), extracted AS (
 SELECT record_sha_hex,source,priority,retrieved_at,
  cast(m['event_id'] AS BIGINT) AS event_id,
  lower(nullif(trim(m['chamber']),'')) AS chamber,
  cast(m['congress'] AS INT) AS congress,
  cast(m['session'] AS SMALLINT) AS session,
  arrow_cast(try_cast(m['updated'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') AS updated,
  nullif(trim(m['title']),'') AS title,
  try_cast(m['meeting_date'] AS DATE) AS meeting_date,
  nullif(trim(m['meeting_type']),'') AS meeting_type,
  nullif(trim(m['status']),'') AS status,
  m['sittings'] AS sittings,
  m['committees'] AS committees,
  m['subject_keys'] AS subject_keys,
  m['transcript_jackets'] AS transcript_jackets,
  m['videos'] AS videos,
  m['collection_states'] AS collection_states
 FROM expanded WHERE m['event_id'] IS NOT NULL
), ranked AS (
 SELECT *,row_number() OVER(
  PARTITION BY event_id,source
  ORDER BY updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,record_sha_hex ASC
 ) AS rn FROM extracted
), current_source AS (
 SELECT *,
  coalesce(nullif(trim(collection_states['sittings']),''),CASE WHEN coalesce(array_length(sittings),0)>0 THEN 'present' ELSE 'absent' END) AS sittings_state,
  coalesce(nullif(trim(collection_states['committees']),''),CASE WHEN coalesce(array_length(committees),0)>0 THEN 'present' ELSE 'absent' END) AS committees_state,
  coalesce(nullif(trim(collection_states['transcript_jackets']),''),CASE WHEN coalesce(array_length(transcript_jackets),0)>0 THEN 'present' ELSE 'absent' END) AS jackets_state,
  coalesce(nullif(trim(collection_states['videos']),''),CASE WHEN coalesce(array_length(videos),0)>0 THEN 'present' ELSE 'absent' END) AS videos_state
 FROM ranked WHERE rn=1
), event_keys AS (
 SELECT DISTINCT event_id FROM current_source
), merged AS (
 SELECT k.event_id,
  coalesce(h.chamber,c.chamber) AS chamber,
  coalesce(h.congress,c.congress) AS congress,
  coalesce(h.session,c.session) AS session,
  coalesce(h.updated,c.updated) AS updated,
  coalesce(h.title,c.title) AS title,
  coalesce(h.meeting_date,c.meeting_date) AS meeting_date,
  coalesce(h.meeting_type,c.meeting_type) AS meeting_type,
  coalesce(h.status,c.status) AS status,
  CASE WHEN h.sittings_state='present' THEN h.sittings
       WHEN h.sittings_state IN ('empty','unrecognized') THEN NULL
       WHEN c.sittings_state='present' THEN c.sittings END AS raw_sittings,
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
 LEFT JOIN current_source h ON k.event_id=h.event_id AND h.source='house_xml'
 LEFT JOIN current_source c ON k.event_id=c.event_id AND c.source='congress_gov'
), sitting_rows AS (
 SELECT event_id,unnest(raw_sittings) AS s,
  unnest(range(0,cast(array_length(raw_sittings) AS BIGINT))) AS idx
 FROM merged WHERE raw_sittings IS NOT NULL AND coalesce(array_length(raw_sittings),0)>0
), sittings_agg AS (
 SELECT event_id,array_agg(named_struct(
  'start',arrow_cast(try_cast(s['start'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))'),
  'end',arrow_cast(try_cast(s['end'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))'),
  'place',nullif(concat_ws(', ',nullif(trim(s['room']),''),nullif(trim(s['building']),''),nullif(trim(s['address']),'')),'')
 ) ORDER BY idx) AS sittings
 FROM sitting_rows GROUP BY event_id
), committee_rows AS (
 SELECT event_id,unnest(raw_committees) AS c,
  unnest(range(0,cast(array_length(raw_committees) AS BIGINT))) AS idx
 FROM merged WHERE raw_committees IS NOT NULL AND coalesce(array_length(raw_committees),0)>0
), committees_agg AS (
 SELECT event_id,array_agg(named_struct(
  'system_code',CASE
   WHEN lower(c['system_code'])='hszt00' THEN 'htzt00'
   WHEN regexp_like(lower(c['system_code']),'^hs(?:cn|ef|fd|gw|hk|ie|ig|ij|mh|qj|rk|vc|zi|zs)[0-9]{2}$')
    THEN 'hl'||substr(lower(c['system_code']),3)
   ELSE lower(c['system_code'])
  END,
  'role',c['role']
 ) ORDER BY idx) AS committees
 FROM committee_rows WHERE c['system_code'] IS NOT NULL GROUP BY event_id
), subject_rows AS (
 SELECT event_id,lower(trim(unnest(house_subjects))) AS subject_key
 FROM merged WHERE house_subjects IS NOT NULL AND coalesce(array_length(house_subjects),0)>0
 UNION ALL
 SELECT event_id,lower(trim(unnest(congress_subjects))) AS subject_key
 FROM merged WHERE congress_subjects IS NOT NULL AND coalesce(array_length(congress_subjects),0)>0
), subjects_agg AS (
 SELECT event_id,array_sort(array_distinct(array_agg(subject_key))) AS subject_keys
 FROM subject_rows WHERE subject_key IS NOT NULL AND subject_key<>'' GROUP BY event_id
), jacket_rows AS (
 SELECT event_id,cast(unnest(raw_jackets) AS BIGINT) AS jacket
 FROM merged WHERE raw_jackets IS NOT NULL AND coalesce(array_length(raw_jackets),0)>0
), jackets_agg AS (
 SELECT event_id,array_sort(array_distinct(array_agg(jacket))) AS transcript_jackets
 FROM jacket_rows WHERE jacket IS NOT NULL GROUP BY event_id
), video_unnested AS (
 SELECT event_id,unnest(raw_videos) AS v,
  unnest(range(0,cast(array_length(raw_videos) AS BIGINT))) AS idx
 FROM merged WHERE raw_videos IS NOT NULL AND coalesce(array_length(raw_videos),0)>0
), video_rows AS (
 SELECT event_id,idx,
  v['title'] AS video_title,
  v['url'] AS video_url,
  nullif(trim(v['video_key']),'') AS explicit_video_key
 FROM video_unnested
), video_matched AS (
 SELECT vr.event_id,vr.idx,vr.video_title AS name,vr.video_url AS url,
  coalesce(vr.explicit_video_key,
   min(regexp_replace((regexp_match(vr.video_url,rs.pattern))[1],'^(.+)$',rs.key_template))
  ) AS video_key
 FROM video_rows vr
 LEFT JOIN recording_sources rs ON rs.kind='video_url' AND vr.video_url IS NOT NULL AND regexp_like(vr.video_url,rs.pattern)
 GROUP BY vr.event_id,vr.idx,vr.video_title,vr.video_url,vr.explicit_video_key
), videos_agg AS (
 SELECT event_id,array_agg(named_struct(
  'name',name,'url',url,'video_key',video_key
 ) ORDER BY idx) AS videos
 FROM video_matched GROUP BY event_id
)
SELECT m.event_id,m.chamber,m.congress,m.session,m.updated,m.title,m.meeting_date,m.meeting_type,m.status,
 coalesce(sa.sittings,array_slice(make_array(named_struct(
  'start',arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))'),
  'end',arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))'),
  'place',cast(NULL AS VARCHAR))),1,0)) AS sittings,
 coalesce(ca.committees,array_slice(make_array(named_struct(
  'system_code',cast(NULL AS VARCHAR),'role',cast(NULL AS VARCHAR))),1,0)) AS committees,
 coalesce(sba.subject_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS subject_keys,
 coalesce(ja.transcript_jackets,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')) AS transcript_jackets,
 coalesce(va.videos,array_slice(make_array(named_struct(
  'name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)) AS videos
FROM merged m
LEFT JOIN sittings_agg sa ON m.event_id=sa.event_id
LEFT JOIN committees_agg ca ON m.event_id=ca.event_id
LEFT JOIN subjects_agg sba ON m.event_id=sba.event_id
LEFT JOIN jackets_agg ja ON m.event_id=ja.event_id
LEFT JOIN videos_agg va ON m.event_id=va.event_id
