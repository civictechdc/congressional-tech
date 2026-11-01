-- Its own materialized step: the steps after it read this many times, and the engine
-- inlines a CTE per reader, so one statement evaluated this ranking and captures join 21 times.
WITH pinned_meeting_versions AS (
 SELECT DISTINCT parser,version FROM parser_versions WHERE parser LIKE 'meeting_records.%'
), selected_meeting_records AS (
 -- An equality key exists: a pinned job selects by (parser, version). Only an unpinned job takes all.
 SELECT r.*
 FROM meeting_records_input r
 JOIN pinned_meeting_versions v ON v.parser=concat('meeting_records.',r.source) AND v.version=r.parser_version
 UNION ALL
 SELECT r.*
 FROM meeting_records_input r
 WHERE (SELECT count(*) FROM pinned_meeting_versions)=0
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
  nullif(trim(m['updated']),'') AS updated_literal,
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
), current_source_final AS (
 SELECT * FROM current_source
)
SELECT * FROM current_source_final
