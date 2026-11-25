-- Incrementally emit batched Wikidata reconciliation GET URLs (10 queries per URL)
-- only for org_bags with no RefSpec registry match and no existing wikidata/reconcile receipt (ct-39u8).
WITH reconcile_url_fetches AS (
 SELECT
  split_part(split_part(c.requested_url,'queries=',2),'#',1) AS encoded_queries
 FROM captures c
 WHERE c.family='wikidata/reconcile'
  AND c.mode='fetch'
  AND c.outcome IN ('stored','unchanged')
  AND c.requested_url LIKE '%queries=%'
), decoded_queries AS (
 SELECT percent_decode_utf8(encoded_queries) AS queries_json
 FROM reconcile_url_fetches
 WHERE nullif(encoded_queries,'') IS NOT NULL
), capture_keys AS (
 SELECT DISTINCT unnest(json_object_keys(queries_json)) AS bag_key
 FROM decoded_queries
 WHERE starts_with(trim(queries_json),'{')
), body_keys AS (
 SELECT DISTINCT bag_key
 FROM wikidata_reconcile_bodies
), registry_keys AS (
 SELECT DISTINCT bag_key
 FROM org_bag_registry_matches
 WHERE bag_key IS NOT NULL
), excluded_bags AS (
 SELECT bag_key FROM capture_keys WHERE nullif(bag_key,'') IS NOT NULL
 UNION
 SELECT bag_key FROM body_keys
 UNION
 SELECT bag_key FROM registry_keys
), candidate_bags AS (
 SELECT
  b.bag_key,
  b.l2_text,
  b.display_text,
  b.appearance_count
 FROM excluded_bags e
 RIGHT ANTI JOIN org_bags b ON b.bag_key=e.bag_key
), queries_prepared AS (
 SELECT
  bag_key,
  appearance_count,
  trim(regexp_replace(
   trim(regexp_replace(
    trim(coalesce(nullif(trim(l2_text),''),trim(display_text),'')),
    '^(?:(?:director|deputy|assistant|associate|chief|chair(?:man|woman|person)?|president|vice president|ceo|cfo|coo|counsel|office of|division(?: of)?|branch(?: of)?|section(?: of)?|bureau of|program(?: of)?|department(?: of)?|subcommittee(?: on)?|committee(?: on)?|on behalf of|board of directors|governmental affairs|government relations|public policy|regulatory affairs|external affairs)[^,]*,\s*)+',
    ''
   )),
   '\s+(?:and|of|for|the|in|on|at|to)$',
   ''
  )) AS query_text
 FROM candidate_bags
), non_empty_queries AS (
 SELECT
  bag_key,
  query_text,
  appearance_count,
  row_number() OVER (ORDER BY appearance_count DESC,bag_key ASC) AS rn
 FROM queries_prepared
 WHERE nullif(query_text,'') IS NOT NULL
  AND length(regexp_replace(query_text,'[^a-z0-9]','','g'))>=3
  AND NOT regexp_like(query_text,'^(?:prepared|prepared statement|written statement|statement|testimony|submitted|for the record|none|n a|na|self|retired|private citizen|individual|independent|witness|member|chairman|president|director|professor|attorney|counsel)$')
), batched AS (
 SELECT
  cast((rn-1)/10 AS BIGINT) AS batch_id,
  bag_key,
  appearance_count,
  json_array(query_text) AS query_json_arr
 FROM non_empty_queries
), batch_entries AS (
 SELECT
  batch_id,
  bag_key,
  appearance_count,
  '"'||bag_key||'":{"limit":5,"query":'||substr(query_json_arr,2,length(query_json_arr)-2)||'}' AS entry_json
 FROM batched
), aggregated AS (
 SELECT
  batch_id,
  array_agg(bag_key ORDER BY bag_key ASC) AS bag_keys,
  cast(count(*) AS BIGINT) AS batch_size,
  cast(sum(appearance_count) AS BIGINT) AS total_appearances,
  '{'||string_agg(entry_json,',' ORDER BY bag_key ASC)||'}' AS queries_json
 FROM batch_entries
 GROUP BY batch_id
), encoded AS (
 SELECT
  batch_id,
  bag_keys,
  batch_size,
  total_appearances,
  queries_json,
  uri_normalize_encoding(replace(replace(queries_json,'%','%25'),'#','%23')) AS norm_queries
 FROM aggregated
)
SELECT
 batch_id,
 bag_keys,
 batch_size,
 total_appearances,
 queries_json,
 'https://wikidata-reconciliation.wmcloud.org/en/api?queries='||replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(
  norm_queries,
  ':','%3A'),',','%2C'),'&','%26'),'+','%2B'),'=','%3D'),'?','%3F'),'/','%2F'),';','%3B'),'@','%40'),'$','%24'),'!','%21'),'''','%27'),'(','%28'),')','%29'),'*','%2A') AS request_url
FROM encoded
ORDER BY batch_id ASC
