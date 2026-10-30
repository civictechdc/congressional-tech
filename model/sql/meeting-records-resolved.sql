WITH fetch_times AS (
 SELECT encode(sha256,'hex') AS record_sha_hex,
  max(arrow_cast(cast(retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS retrieved_at
 FROM captures
 WHERE sha256 IS NOT NULL AND mode='fetch' AND complete AND outcome IN ('stored','unchanged') AND http_status BETWEEN 200 AND 299
 GROUP BY sha256
), expanded AS (
 SELECT r.record_sha_hex,r.source,ms.priority,f.retrieved_at,unnest(r.meetings) AS m
 FROM meeting_records_input r
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
  m['videos'] AS videos
 FROM expanded WHERE m['event_id'] IS NOT NULL
), ranked AS (
 SELECT *,row_number() OVER(
  PARTITION BY event_id,source
  ORDER BY updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,record_sha_hex ASC
 ) AS rn FROM extracted
), current_source AS (
 SELECT * FROM ranked WHERE rn=1
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
  CASE WHEN coalesce(array_length(h.sittings),0)>0 THEN h.sittings
       WHEN coalesce(array_length(c.sittings),0)>0 THEN c.sittings END AS raw_sittings,
  CASE WHEN coalesce(array_length(h.committees),0)>0 THEN h.committees
       WHEN coalesce(array_length(c.committees),0)>0 THEN c.committees END AS raw_committees,
  CASE WHEN coalesce(array_length(h.subject_keys),0)>0 THEN h.subject_keys
       WHEN coalesce(array_length(c.subject_keys),0)>0 THEN c.subject_keys END AS raw_subjects,
  CASE WHEN coalesce(array_length(h.transcript_jackets),0)>0 THEN h.transcript_jackets
       WHEN coalesce(array_length(c.transcript_jackets),0)>0 THEN c.transcript_jackets END AS raw_jackets,
  CASE WHEN coalesce(array_length(h.videos),0)>0 THEN h.videos
       WHEN coalesce(array_length(c.videos),0)>0 THEN c.videos END AS raw_videos
 FROM event_keys k
 LEFT JOIN current_source h ON k.event_id=h.event_id AND h.source='house_xml'
 LEFT JOIN current_source c ON k.event_id=c.event_id AND c.source='congress_gov'
), sitting_rows AS (
 SELECT event_id,unnest(raw_sittings) AS s,
  unnest(range(0,cast(array_length(raw_sittings) AS BIGINT))) AS idx
 FROM merged WHERE raw_sittings IS NOT NULL
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
 FROM merged WHERE raw_committees IS NOT NULL
), committees_agg AS (
 SELECT event_id,array_agg(named_struct(
  'system_code',lower(c['system_code']),
  'role',c['role']
 ) ORDER BY idx) AS committees
 FROM committee_rows WHERE c['system_code'] IS NOT NULL GROUP BY event_id
), subject_rows AS (
 SELECT event_id,lower(trim(unnest(raw_subjects))) AS subject_key
 FROM merged WHERE raw_subjects IS NOT NULL
), subjects_agg AS (
 SELECT event_id,array_sort(array_distinct(array_agg(subject_key))) AS subject_keys
 FROM subject_rows WHERE subject_key IS NOT NULL AND subject_key<>'' GROUP BY event_id
), jacket_rows AS (
 SELECT event_id,cast(unnest(raw_jackets) AS BIGINT) AS jacket
 FROM merged WHERE raw_jackets IS NOT NULL
), jackets_agg AS (
 SELECT event_id,array_sort(array_distinct(array_agg(jacket))) AS transcript_jackets
 FROM jacket_rows WHERE jacket IS NOT NULL GROUP BY event_id
), video_unnested AS (
 SELECT event_id,unnest(raw_videos) AS v,
  unnest(range(0,cast(array_length(raw_videos) AS BIGINT))) AS idx
 FROM merged WHERE raw_videos IS NOT NULL
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
