-- Its own materialized step: the steps after it read this many times, and the engine
-- inlines a CTE per reader, so one statement evaluated this ranking and captures join 21 times.
-- Keeps each (event, source)'s current record and the records sharing its updated, with the
-- row number of the record each collection comes from (meeting-records-current joins them back).
WITH candidate_meeting_shas AS (
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
  m['document_urls'] AS document_urls,
  m['collection_states'] AS collection_states,
  m['access'] AS access,
  m['access_basis'] AS access_basis,
  m['not_held'] AS not_held,
  m['title_key'] AS title_key,
  m['reschedule_candidate'] AS reschedule_candidate
 FROM expanded WHERE m['event_id'] IS NOT NULL
), ranked AS (
 SELECT *,row_number() OVER(
  PARTITION BY event_id,source
  ORDER BY updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,record_sha_hex ASC
 ) AS rn,first_value(updated) OVER(
  PARTITION BY event_id,source
  ORDER BY updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,record_sha_hex ASC
 ) AS current_updated FROM extracted
), stated AS (
 SELECT *,
  coalesce(nullif(trim(collection_states['sittings']),''),CASE WHEN coalesce(array_length(sittings),0)>0 THEN 'present' ELSE 'absent' END) AS sittings_state,
  coalesce(nullif(trim(collection_states['committees']),''),CASE WHEN coalesce(array_length(committees),0)>0 THEN 'present' ELSE 'absent' END) AS committees_state,
  coalesce(nullif(trim(collection_states['subject_keys']),''),CASE WHEN coalesce(array_length(subject_keys),0)>0 THEN 'present' ELSE 'absent' END) AS subjects_state,
  coalesce(nullif(trim(collection_states['transcript_jackets']),''),CASE WHEN coalesce(array_length(transcript_jackets),0)>0 THEN 'present' ELSE 'absent' END) AS jackets_state,
  coalesce(nullif(trim(collection_states['videos']),''),CASE WHEN coalesce(array_length(videos),0)>0 THEN 'present' ELSE 'absent' END) AS videos_state,
  coalesce(nullif(trim(collection_states['document_urls']),''),CASE WHEN coalesce(array_length(document_urls),0)>0 THEN 'present' ELSE 'absent' END) AS document_urls_state
 FROM ranked WHERE updated IS NOT DISTINCT FROM current_updated
), picked AS (
 -- Congress.gov omits a collection it has none of, so an omission under a later updated replaces the list.
 -- Records sharing the current updated state no change between them: a collection the current record
 -- omits comes from the best-ranked record of that stamp that states it (ct-5kk7). Empty and
 -- unrecognized never fall back. Windows pick row numbers only: the pinned engine's first_value over
 -- a nested list drops its element metadata from the array but not the schema.
 SELECT *,
  first_value(rn) OVER (PARTITION BY event_id,source ORDER BY sittings_state='absent',rn) AS sittings_rn,
  first_value(rn) OVER (PARTITION BY event_id,source ORDER BY committees_state='absent',rn) AS committees_rn,
  first_value(rn) OVER (PARTITION BY event_id,source ORDER BY subjects_state='absent',rn) AS subjects_rn,
  first_value(rn) OVER (PARTITION BY event_id,source ORDER BY jackets_state='absent',rn) AS jackets_rn,
  first_value(rn) OVER (PARTITION BY event_id,source ORDER BY videos_state='absent',rn) AS videos_rn,
  first_value(rn) OVER (PARTITION BY event_id,source ORDER BY document_urls_state='absent',rn) AS document_urls_rn
 FROM stated
)
SELECT * FROM picked
WHERE rn=1 OR rn IN (sittings_rn,committees_rn,subjects_rn,jackets_rn,videos_rn,document_urls_rn)
