WITH combined AS (
 SELECT source_id,meeting_key,chamber FROM source_annotation_addresses WHERE meeting_key IS NOT NULL
 -- The publisher's own meeting record lists this file (ct-66ns).
 UNION SELECT c.source_id,cast(d.event_id AS VARCHAR) AS meeting_key,cast(NULL AS VARCHAR) AS chamber
 FROM meeting_document_urls d JOIN model_url_keys k ON k.url=d.url AND k.error IS NULL
 JOIN copy_url_keys c ON c.url_key=k.url_key
)
SELECT source_id,array_sort(array_distinct(array_agg(cast(try_cast(meeting_key AS BIGINT) AS VARCHAR)))) AS meeting_keys,
 array_sort(array_distinct(array_agg(chamber) FILTER(WHERE chamber IS NOT NULL))) AS chambers
FROM combined WHERE try_cast(meeting_key AS BIGINT) IS NOT NULL GROUP BY source_id
