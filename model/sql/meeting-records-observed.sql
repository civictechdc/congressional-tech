-- All pinned, completed meeting observations before current-field selection.
-- Materialize once: ranking and published status history share this extraction and capture join.
WITH candidate_meeting_shas AS (
 SELECT DISTINCT record_sha_hex
 FROM selected_meeting_records
 WHERE record_sha_hex IS NOT NULL
), fetch_times AS (
 SELECT encode(c.sha256,'hex') AS record_sha_hex,
  min(arrow_cast(cast(c.retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS first_retrieved_at,
  max(arrow_cast(cast(c.retrieved_at AS TIMESTAMP WITH TIME ZONE),'Timestamp(Microsecond, Some("UTC"))')) AS retrieved_at
 FROM captures c
 JOIN candidate_meeting_shas cms ON encode(c.sha256,'hex')=cms.record_sha_hex
 WHERE c.sha256 IS NOT NULL AND c.mode='fetch' AND c.complete AND c.outcome IN ('stored','unchanged') AND c.http_status BETWEEN 200 AND 299
 GROUP BY c.sha256
), expanded AS (
 SELECT r.record_sha_hex,r.source,ms.priority,f.first_retrieved_at,f.retrieved_at,unnest(r.meetings) AS m
 FROM selected_meeting_records r
 JOIN meeting_sources ms ON ms.kind='meeting' AND r.source=ms.source
 LEFT JOIN fetch_times f ON r.record_sha_hex=f.record_sha_hex
 WHERE r.status='completed' AND r.meetings IS NOT NULL
), extracted AS (
 SELECT record_sha_hex,source,priority,first_retrieved_at,retrieved_at,
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
  m['document_references'] AS document_references,
  m['collection_states'] AS collection_states,
  m['access'] AS access,
  m['access_basis'] AS access_basis,
  m['not_held'] AS not_held,
  m['title_key'] AS title_key,
  m['reschedule_candidate'] AS reschedule_candidate
 FROM expanded WHERE m['event_id'] IS NOT NULL
)
SELECT * FROM extracted
