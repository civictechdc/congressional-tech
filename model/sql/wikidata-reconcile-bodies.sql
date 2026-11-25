-- Extract parsed Wikidata reconciliation candidates from retained wikidata/reconcile
-- responses (ct-39u8). Filters captures for wikidata/reconcile fetch SHAs first so
-- DataFusion pushes the candidate SHA set into selected_readings.
WITH reconcile_fetches AS (
 SELECT
  c.sha256,
  c.receipt_key,
  c.retrieved_at
 FROM captures c
 WHERE c.family='wikidata/reconcile'
  AND c.mode='fetch'
  AND c.outcome IN ('stored','unchanged')
  AND c.sha256 IS NOT NULL
), latest_fetches AS (
 SELECT
  sha256,
  receipt_key,
  retrieved_at,
  row_number() OVER (
   PARTITION BY sha256
   ORDER BY retrieved_at DESC NULLS LAST,receipt_key DESC
  ) AS rn
 FROM reconcile_fetches
), candidate_shas AS (
 SELECT
  sha256 AS body_sha,
  encode(sha256,'hex') AS receipt_sha,
  receipt_key,
  retrieved_at
 FROM latest_fetches
 WHERE rn=1
), matched_readings AS (
 SELECT
  cs.receipt_sha,
  cs.receipt_key,
  cs.retrieved_at,
  r.fields
 FROM candidate_shas cs
 JOIN selected_readings r ON r.body_sha=cs.body_sha
 WHERE r.parser='wikidata_reconcile'
  AND r.status='completed'
), query_fields AS (
 SELECT
  receipt_sha,
  receipt_key,
  retrieved_at,
  substr(f['field'],7) AS bag_key,
  json_get_array(f['value']) AS candidates
 FROM (
  SELECT
   receipt_sha,
   receipt_key,
   retrieved_at,
   unnest(fields) AS f
  FROM matched_readings
 )
 WHERE starts_with(f['field'],'query:')
  AND f['value'] IS NOT NULL
), exploded AS (
 SELECT
  receipt_sha,
  receipt_key,
  retrieved_at,
  bag_key,
  unnest(candidates) AS cand
 FROM query_fields
 WHERE candidates IS NOT NULL
  AND cardinality(candidates)>0
)
SELECT
 bag_key,
 json_get_str(cand,'id') AS qid,
 json_get_str(cand,'name') AS candidate_name,
 json_get_str(cand,'description') AS candidate_description,
 cast(json_get_float(cand,'score') AS DOUBLE) AS score,
 coalesce(json_get_bool(cand,'match'),false) AS api_match,
 CASE
  WHEN coalesce(cardinality(json_get_array(cand,'types')),0)>0
  THEN string_to_array(replace(array_to_string(json_get_array(cand,'types'),','),'"',''),',')
  ELSE arrow_cast(array_slice(make_array(cast(NULL AS VARCHAR)),1,0),'List(Utf8)')
 END AS cand_types,
 receipt_sha,
 receipt_key,
 retrieved_at
FROM exploded
WHERE nullif(trim(bag_key),'') IS NOT NULL
 AND nullif(trim(json_get_str(cand,'id')),'') IS NOT NULL
 AND json_get_float(cand,'score') IS NOT NULL
