WITH sitting_rows AS (
 SELECT event_id,sittings_are_eastern,unnest(raw_sittings) AS s,
  unnest(range(0,cast(array_length(raw_sittings) AS BIGINT))) AS idx
 FROM meeting_records_merged WHERE raw_sittings IS NOT NULL AND coalesce(array_length(raw_sittings),0)>0
), sittings_agg AS (
 SELECT event_id,array_agg(named_struct(
  'start',CASE WHEN sittings_are_eastern AND NOT regexp_like(s['start'],'T.*(Z|[+-][0-9:]+)$') THEN arrow_cast(try_cast(s['start'] AS TIMESTAMP) AT TIME ZONE 'America/New_York','Timestamp(Microsecond, Some("UTC"))')
   ELSE arrow_cast(try_cast(s['start'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') END,
  'end',CASE WHEN sittings_are_eastern AND NOT regexp_like(s['end'],'T.*(Z|[+-][0-9:]+)$') THEN arrow_cast(try_cast(s['end'] AS TIMESTAMP) AT TIME ZONE 'America/New_York','Timestamp(Microsecond, Some("UTC"))')
   ELSE arrow_cast(try_cast(s['end'] AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') END,
  'place',nullif(concat_ws(', ',nullif(trim(s['room']),''),nullif(trim(s['building']),''),nullif(trim(s['address']),'')),''),
  'room',nullif(trim(s['room']),''),
  'building',nullif(trim(s['building']),''),
  'address',nullif(trim(s['address']),'')
 ) ORDER BY idx) AS sittings
 FROM sitting_rows GROUP BY event_id
), committee_rows AS (
 SELECT event_id,unnest(raw_committees) AS c,
  unnest(range(0,cast(array_length(raw_committees) AS BIGINT))) AS idx
 FROM meeting_records_merged WHERE raw_committees IS NOT NULL AND coalesce(array_length(raw_committees),0)>0
), committee_codes AS (
 -- Computed before the aggregate: this CASE inside an ordered array_agg took 15-19 GiB RSS
 -- on 2,900 rows under a 1 GiB pool, and precomputed it costs almost nothing.
 SELECT event_id,idx,c['role'] AS role,CASE
   WHEN lower(c['system_code'])='hszt00' THEN 'htzt00'
   WHEN regexp_like(lower(c['system_code']),'^hs(?:cn|ef|fd|gw|hk|ie|ig|ij|mh|qj|rk|vc|zi|zs)[0-9]{2}$')
    THEN 'hl'||substr(lower(c['system_code']),3)
   ELSE lower(c['system_code'])
  END AS system_code
 FROM committee_rows WHERE c['system_code'] IS NOT NULL
), committees_agg AS (
 SELECT event_id,array_agg(named_struct('system_code',system_code,'role',role) ORDER BY idx) AS committees
 FROM committee_codes GROUP BY event_id
), subject_rows AS (
 SELECT event_id,lower(trim(unnest(house_subjects))) AS subject_key
 FROM meeting_records_merged WHERE house_subjects IS NOT NULL AND coalesce(array_length(house_subjects),0)>0
 UNION ALL
 SELECT event_id,lower(trim(unnest(congress_subjects))) AS subject_key
 FROM meeting_records_merged WHERE congress_subjects IS NOT NULL AND coalesce(array_length(congress_subjects),0)>0
), subjects_agg AS (
 SELECT event_id,array_sort(array_distinct(array_agg(subject_key))) AS subject_keys
 FROM subject_rows WHERE subject_key IS NOT NULL AND subject_key<>'' GROUP BY event_id
), jacket_rows AS (
 SELECT event_id,cast(unnest(raw_jackets) AS BIGINT) AS jacket
 FROM meeting_records_merged WHERE raw_jackets IS NOT NULL AND coalesce(array_length(raw_jackets),0)>0
), jackets_agg AS (
 SELECT event_id,array_sort(array_distinct(array_agg(jacket))) AS transcript_jackets
 FROM jacket_rows WHERE jacket IS NOT NULL GROUP BY event_id
), video_unnested AS (
 SELECT event_id,unnest(raw_videos) AS v,
  unnest(range(0,cast(array_length(raw_videos) AS BIGINT))) AS idx
 FROM meeting_records_merged WHERE raw_videos IS NOT NULL AND coalesce(array_length(raw_videos),0)>0
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
SELECT m.event_id,m.chamber,m.congress,m.session,m.updated,m.congress_gov_updated,m.house_xml_updated,m.congress_gov_meeting_type,m.title,m.meeting_date,m.meeting_type,m.status,
 coalesce(sa.sittings,array_slice(make_array(named_struct(
  'start',arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))'),
  'end',arrow_cast(NULL,'Timestamp(Microsecond, Some("UTC"))'),
  'place',cast(NULL AS VARCHAR),'room',cast(NULL AS VARCHAR),'building',cast(NULL AS VARCHAR),'address',cast(NULL AS VARCHAR))),1,0)) AS sittings,
 coalesce(ca.committees,array_slice(make_array(named_struct(
  'system_code',cast(NULL AS VARCHAR),'role',cast(NULL AS VARCHAR))),1,0)) AS committees,
 coalesce(sba.subject_keys,arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')) AS subject_keys,
 coalesce(ja.transcript_jackets,arrow_cast(array_slice(make_array(cast(NULL AS BIGINT)),1,0),'List(Int64)')) AS transcript_jackets,
 coalesce(va.videos,array_slice(make_array(named_struct(
  'name',cast(NULL AS VARCHAR),'url',cast(NULL AS VARCHAR),'video_key',cast(NULL AS VARCHAR))),1,0)) AS videos
FROM meeting_records_merged m
LEFT JOIN sittings_agg sa ON m.event_id=sa.event_id
LEFT JOIN committees_agg ca ON m.event_id=ca.event_id
LEFT JOIN subjects_agg sba ON m.event_id=sba.event_id
LEFT JOIN jackets_agg ja ON m.event_id=ja.event_id
LEFT JOIN videos_agg va ON m.event_id=va.event_id
