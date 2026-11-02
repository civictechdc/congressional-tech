WITH sitting_rows AS (
 SELECT event_id,house_sitting AS h,unnest(raw_sittings) AS s,
  unnest(range(0,cast(array_length(raw_sittings) AS BIGINT))) AS idx
 FROM meeting_records_merged WHERE raw_sittings IS NOT NULL AND coalesce(array_length(raw_sittings),0)>0
), sitting_fields AS (
 -- A first sitting fills each fact Congress.gov lacks from the House record, field by field.
 SELECT event_id,idx,
  nullif(trim(s['start']),'') AS start_text,
  CASE WHEN same_start THEN coalesce(nullif(trim(s['end']),''),nullif(trim(h['end']),'')) ELSE nullif(trim(s['end']),'') END AS end_text,
  CASE WHEN same_start THEN coalesce(nullif(trim(s['room']),''),nullif(trim(h['room']),'')) ELSE nullif(trim(s['room']),'') END AS room,
  CASE WHEN same_start THEN coalesce(nullif(trim(s['building']),''),nullif(trim(h['building']),'')) ELSE nullif(trim(s['building']),'') END AS building,
  CASE WHEN same_start THEN coalesce(nullif(trim(s['address']),''),nullif(trim(h['address']),'')) ELSE nullif(trim(s['address']),'') END AS address
 FROM (SELECT *,idx=0 AND try_cast(s['start'] AS TIMESTAMP WITH TIME ZONE)=try_cast(h['start'] AS TIMESTAMP WITH TIME ZONE) AS same_start FROM sitting_rows)
), sittings_agg AS (
 SELECT event_id,array_agg(named_struct(
  'start',start_ts,
  'end',end_ts,
  'place',nullif(concat_ws(', ',room,building,address),''),
  'room',room,
  'building',building,
  'address',address
 ) ORDER BY idx) AS sittings
 FROM (
  -- Computed here, not in the aggregate: a computed CASE branch in an ordered array_agg exceeds the pool.
  -- A date alone states no instant, so it must not become UTC midnight.
  SELECT *,CASE WHEN start_text LIKE '%T%' THEN arrow_cast(try_cast(start_text AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') END AS start_ts,CASE WHEN end_text LIKE '%T%' THEN arrow_cast(try_cast(end_text AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))') END AS end_ts FROM sitting_fields
 ) GROUP BY event_id
), committee_rows AS (
 SELECT event_id,unnest(raw_committees) AS c,
  unnest(range(0,cast(array_length(raw_committees) AS BIGINT))) AS idx
 FROM meeting_records_merged WHERE raw_committees IS NOT NULL AND coalesce(array_length(raw_committees),0)>0
), committee_codes AS (
 -- Computed before the aggregate: this CASE inside an ordered array_agg took 15-19 GiB RSS
 -- on 2,900 rows under a 1 GiB pool, and precomputed it costs almost nothing. House select and
 -- task-force codes (hs* -> hl*) are normalized once, by meeting_records.py; an SQL copy of that rule
 -- matched 0 of 18,183 Congress.gov and 6,287 House XML codes on v21 (ct-p3ff).
 SELECT event_id,idx,c['role'] AS role,CASE
   WHEN lower(c['system_code'])='hszt00' THEN 'htzt00'
   ELSE lower(c['system_code'])
  END AS system_code
 FROM committee_rows WHERE c['system_code'] IS NOT NULL
), committees_agg AS (
 SELECT event_id,array_agg(named_struct('system_code',system_code,'role',role) ORDER BY idx) AS committees
 FROM committee_codes GROUP BY event_id
), committee_keys AS (
 SELECT event_id,array_to_string(array_sort(array_agg(DISTINCT system_code)),';') AS committee_key
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
SELECT m.event_id,m.chamber,m.congress,m.session,m.updated,m.congress_gov_updated,m.house_xml_updated,m.congress_gov_meeting_type,m.access,m.access_basis,m.not_held,m.title_key,m.reschedule_candidate,ck.committee_key,m.title,m.meeting_date,m.meeting_type,m.status,
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
LEFT JOIN committee_keys ck ON m.event_id=ck.event_id
LEFT JOIN subjects_agg sba ON m.event_id=sba.event_id
LEFT JOIN jackets_agg ja ON m.event_id=ja.event_id
LEFT JOIN videos_agg va ON m.event_id=va.event_id
