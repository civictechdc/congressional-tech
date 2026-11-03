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
), meeting_committee_codes AS (
 -- Computed before the aggregate: an expression inside an ordered array_agg took 15-19 GiB RSS
 -- on 2,900 rows under a 1 GiB pool. Committee codes are normalized once, by meeting_records.py
 -- (hs* select -> hl*, hszt -> htzt); the SQL copies matched 0 of 18,183 Congress.gov and 6,287
 -- House XML codes on v21 (ct-p3ff), so the model only lowercases.
 SELECT event_id,idx,c['role'] AS role,lower(c['system_code']) AS system_code
 FROM committee_rows WHERE c['system_code'] IS NOT NULL
), committees_agg AS (
 SELECT event_id,array_agg(named_struct('system_code',system_code,'role',role) ORDER BY idx) AS committees
 FROM meeting_committee_codes GROUP BY event_id
), committee_keys AS (
 SELECT event_id,array_to_string(array_sort(array_agg(DISTINCT system_code)),';') AS committee_key
 FROM meeting_committee_codes GROUP BY event_id
), held_meeting_committees AS (
 SELECT DISTINCT m.event_id,m.congress,m.meeting_date,mc.system_code AS sys_code
 FROM meeting_records_merged m
 JOIN meeting_committee_codes mc ON mc.event_id=m.event_id
 WHERE NOT coalesce(m.not_held,false) AND m.meeting_date IS NOT NULL
 UNION
 SELECT DISTINCT m.event_id,m.congress,m.meeting_date,substr(mc.system_code,1,4)||'00' AS sys_code
 FROM meeting_records_merged m
 JOIN meeting_committee_codes mc ON mc.event_id=m.event_id
 WHERE NOT coalesce(m.not_held,false) AND m.meeting_date IS NOT NULL
   AND length(mc.system_code)=6 AND substr(mc.system_code,5,2)<>'00'
), unambiguous_committee_dates AS (
 SELECT sys_code,meeting_date,min(event_id) AS event_id,min(congress) AS congress
 FROM held_meeting_committees
 GROUP BY sys_code,meeting_date
 HAVING count(DISTINCT event_id)=1
), normalized_bill_activities AS (
 SELECT
  lower(trim(a.bill_id)) AS bill_id,
  try_cast(split_part(lower(trim(a.bill_id)),'-',1) AS INT) AS bill_congress,
  lower(trim(a.system_code)) AS sys_code,
  lower(trim(a.activity_name)) AS activity_lower,
  try_cast(substr(trim(a.activity_date),1,10) AS DATE) AS activity_day
 FROM spicy_bill_committee_activities a
 WHERE a.bill_id IS NOT NULL AND trim(a.bill_id)<>''
   AND a.system_code IS NOT NULL AND trim(a.system_code)<>''
), activity_subject_rows AS (
 -- Source 2: unambiguous 1:1 (committee or parent_committee, activity_date) 'Hearings%' or 'Markup%'
 SELECT DISTINCT ucd.event_id,nba.bill_id AS subject_key
 FROM normalized_bill_activities nba
 JOIN unambiguous_committee_dates ucd
  ON ucd.meeting_date=nba.activity_day
 AND (ucd.sys_code=nba.sys_code OR (length(nba.sys_code)=6 AND substr(nba.sys_code,5,2)<>'00' AND ucd.sys_code=substr(nba.sys_code,1,4)||'00'))
 WHERE (nba.activity_lower LIKE 'hearings%' OR nba.activity_lower LIKE 'markup%')
   AND (ucd.congress IS NULL OR nba.bill_congress=ucd.congress)
), orig_bill_meeting_titles AS (
 -- Source 3: Senate/House "original bill entitled '...'" markups
 SELECT
  event_id,
  congress,
  CASE
   WHEN lower(trim(chamber)) IN ('senate','s') THEN 's'
   WHEN lower(trim(chamber)) IN ('house','h','house of representatives') THEN 'hr'
  END AS bill_type,
  trim(regexp_replace(
   regexp_replace(
    regexp_replace(
     regexp_replace(lower(trim(substr(raw_seg,11))),'\s*\([a-z0-9-]+\)','','g'),
     '^the\s+',''
    ),
    '[.,;]+$',''
   ),
   '\s+',' ','g'
  )) AS norm_title
 FROM (
  SELECT event_id,congress,chamber,
   unnest(string_to_array(
    regexp_replace(
     coalesce(title,''),
     '(?i)original\s+bills?\s+entitled[,:\s]*(?:"([^"]+)"|“([^”]+)”|¿([^¿"”]+)[¿"”]|''([^'']+)'')',
     '|||ORIG_BILL:$1$2$3$4|||',
     'g'
    ),
    '|||'
   )) AS raw_seg
  FROM meeting_records_merged
  WHERE title IS NOT NULL AND regexp_like(title,'(?i)original\s+bills?\s+entitled')
 )
 WHERE raw_seg LIKE 'ORIG_BILL:%'
), normalized_congress_bills AS (
 SELECT
  lower(trim(cb.bill_id)) AS bill_id,
  try_cast(split_part(lower(trim(cb.bill_id)),'-',1) AS INT) AS bill_congress,
  split_part(lower(trim(cb.bill_id)),'-',2) AS bill_type,
  trim(regexp_replace(
   regexp_replace(
    regexp_replace(
     regexp_replace(lower(coalesce(cb.title,'')),'\s*\([a-z0-9-]+\)','','g'),
     '^the\s+',''
    ),
    '[.,;]+$',''
   ),
   '\s+',' ','g'
  )) AS norm_title,
  trim(regexp_replace(
   regexp_replace(
    regexp_replace(
     regexp_replace(lower(coalesce(cb.short_title,'')),'\s*\([a-z0-9-]+\)','','g'),
     '^the\s+',''
    ),
    '[.,;]+$',''
   ),
   '\s+',' ','g'
  )) AS norm_short_title
 FROM spicy_congress_bills cb
 WHERE cb.bill_id IS NOT NULL AND trim(cb.bill_id)<>''
), orig_bill_subject_rows AS (
 SELECT DISTINCT ob.event_id,ncb.bill_id AS subject_key
 FROM orig_bill_meeting_titles ob
 JOIN normalized_congress_bills ncb
  ON ncb.bill_congress=ob.congress
 AND (ob.bill_type IS NULL OR ncb.bill_type=ob.bill_type)
 AND (
  ncb.norm_title=ob.norm_title
  OR ncb.norm_short_title=ob.norm_title
  OR regexp_replace(ncb.norm_title,'\s+of\s+20[0-9]{2}$','')=regexp_replace(ob.norm_title,'\s+of\s+20[0-9]{2}$','')
  OR (ncb.norm_short_title<>'' AND regexp_replace(ncb.norm_short_title,'\s+of\s+20[0-9]{2}$','')=regexp_replace(ob.norm_title,'\s+of\s+20[0-9]{2}$',''))
 )
 JOIN meeting_committee_codes mc ON mc.event_id=ob.event_id
 JOIN normalized_bill_activities nba
  ON nba.bill_id=ncb.bill_id
 AND (mc.system_code=nba.sys_code OR substr(mc.system_code,1,4)=substr(nba.sys_code,1,4))
 WHERE ob.norm_title<>''
), title_bill_candidates AS (
 -- Source 5b: explicit bill numbers in meetings.title (ignoring U.S. / D.S. abbreviations)
 SELECT
  event_id,
  cast(congress AS VARCHAR)||'-'||
   regexp_replace(lower(split_part(raw_ref,':',2)),'[^a-z]','','g')||'-'||
   trim(split_part(raw_ref,':',3)) AS bill_id
 FROM (
  SELECT event_id,congress,
   unnest(string_to_array(
    regexp_replace(
     regexp_replace(coalesce(title,''),'(?i)(?:\bU\.\s*S\.(?:\s*C\.)?|\b[A-Za-z]\.\s*S\.)','US','g'),
     '(?i)\b(H\.\s*R\.|S\.|H\.\s*J\.\s*Res\.|S\.\s*J\.\s*Res\.|H\.\s*Con\.\s*Res\.|S\.\s*Con\.\s*Res\.|H\.\s*Res\.|S\.\s*Res\.)\s*([0-9]+)\b',
     '|||BILL_REF:$1:$2|||',
     'g'
    ),
    '|||'
   )) AS raw_ref
  FROM meeting_records_merged
  WHERE congress IS NOT NULL AND title IS NOT NULL
 )
 WHERE raw_ref LIKE 'BILL_REF:%'
), title_bill_subject_rows AS (
 SELECT DISTINCT tbc.event_id,tbc.bill_id AS subject_key
 FROM title_bill_candidates tbc
 JOIN normalized_congress_bills ncb ON ncb.bill_id=tbc.bill_id
), jacket_rows AS (
 SELECT event_id,cast(unnest(raw_jackets) AS BIGINT) AS jacket
 FROM meeting_records_merged WHERE raw_jackets IS NOT NULL AND coalesce(array_length(raw_jackets),0)>0
), jackets_agg AS (
 SELECT event_id,array_sort(array_distinct(array_agg(jacket))) AS transcript_jackets
 FROM jacket_rows WHERE jacket IS NOT NULL GROUP BY event_id
), nomination_jacket_subjects AS (
 -- Source 5a (jacket part): confirmation hearing nominations matched by jacketNumber / jacket_number / package_id
 SELECT DISTINCT jr.event_id,
  cast(n.congress AS VARCHAR)||'-pn-'||cast(n.number AS VARCHAR)||
  CASE
   WHEN n.part_number IS NOT NULL AND try_cast(n.part_number AS INT) IS NOT NULL AND try_cast(n.part_number AS INT)<>0
    THEN '-'||regexp_replace(trim(n.part_number),'^0+','')
   ELSE ''
  END AS subject_key
 FROM jacket_rows jr
 JOIN meeting_records_merged m ON m.event_id=jr.event_id
 JOIN (
  SELECT congress,number,part_number,
   try_cast(coalesce(
    (regexp_match(chunk,'(?i)"jacket(?:_?number)?"\s*:\s*"?([0-9]+)"?'))[1],
    (regexp_match(chunk,'CHRG-[0-9]+[hsj]hrg([0-9]+)'))[1]
   ) AS BIGINT) AS jacket
  FROM (
   SELECT congress,number,part_number,
    unnest(string_to_array(hearings_json,'}')) AS chunk
   FROM spicy_nominations
   WHERE congress IS NOT NULL AND number IS NOT NULL AND hearings_json IS NOT NULL
  )
 ) n ON n.jacket=jr.jacket AND (m.congress IS NULL OR m.congress=n.congress)
 WHERE n.jacket IS NOT NULL
), subject_rows AS (
 SELECT event_id,lower(trim(unnest(house_subjects))) AS subject_key
 FROM meeting_records_merged WHERE house_subjects IS NOT NULL AND coalesce(array_length(house_subjects),0)>0
 UNION ALL
 SELECT event_id,lower(trim(unnest(congress_subjects))) AS subject_key
 FROM meeting_records_merged WHERE congress_subjects IS NOT NULL AND coalesce(array_length(congress_subjects),0)>0
 UNION ALL
 SELECT event_id,subject_key FROM activity_subject_rows
 UNION ALL
 SELECT event_id,subject_key FROM orig_bill_subject_rows
 UNION ALL
 SELECT event_id,subject_key FROM title_bill_subject_rows
 UNION ALL
 SELECT event_id,subject_key FROM nomination_jacket_subjects
), subjects_agg AS (
 SELECT event_id,array_sort(array_distinct(array_agg(subject_key))) AS subject_keys
 FROM subject_rows WHERE subject_key IS NOT NULL AND subject_key<>'' GROUP BY event_id
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
