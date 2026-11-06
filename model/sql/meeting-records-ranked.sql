-- Current-field selection consumes the shared observations without pruning published history.
WITH ranked AS (
 SELECT *,row_number() OVER(
  PARTITION BY event_id,source
  ORDER BY updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,record_sha_hex ASC
 ) AS rn,first_value(updated) OVER(
  PARTITION BY event_id,source
  ORDER BY updated DESC NULLS LAST,retrieved_at DESC NULLS LAST,record_sha_hex ASC
 ) AS current_updated FROM meeting_records_observed
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
