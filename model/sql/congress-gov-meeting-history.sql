-- Congress.gov meeting observations ordered from newest (hist_rn=1) to oldest per event_id (ct-960v).
-- Materialized once so congress_gov_retained_items never re-scans meeting_records_observed.
SELECT o.event_id,o.record_sha_hex,
 coalesce(
  cast(arrow_cast(o.retrieved_at,'Timestamp(Microsecond, None)') AS DATE),
  cast(arrow_cast(o.updated,'Timestamp(Microsecond, None)') AS DATE)
 ) AS obs_date,
 coalesce(
  cast(arrow_cast(coalesce(o.first_retrieved_at,o.retrieved_at),'Timestamp(Microsecond, None)') AS DATE),
  cast(arrow_cast(o.updated,'Timestamp(Microsecond, None)') AS DATE)
 ) AS first_obs_date,
 o.subject_keys,o.document_urls,o.document_references,
 coalesce(nullif(trim(o.collection_states['subject_keys']),''),CASE WHEN coalesce(array_length(o.subject_keys),0)>0 THEN 'present' ELSE 'absent' END) AS subjects_state,
 coalesce(nullif(trim(o.collection_states['document_urls']),''),CASE WHEN coalesce(array_length(o.document_urls),0)>0 THEN 'present' ELSE 'absent' END) AS document_urls_state,
 row_number() OVER(
  PARTITION BY o.event_id
  ORDER BY o.updated DESC NULLS LAST,o.retrieved_at DESC NULLS LAST,o.record_sha_hex ASC
 ) AS hist_rn
FROM meeting_records_observed o
WHERE o.source='congress_gov'
