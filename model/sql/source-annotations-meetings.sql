WITH package_records AS (
 SELECT DISTINCT a.package_id,unnest(p.named_meetings) AS event_id FROM source_annotation_addresses a
 JOIN capture_sources c ON a.source_id=c.source_id AND a.url=c.context_url
 JOIN page_facts p ON c.body_sha=encode(p.body_sha,'hex')
 WHERE a.package_id IS NOT NULL AND NOT a.publisher AND p.status='completed'
), combined AS (
 SELECT source_id,meeting_key,chamber FROM source_annotation_addresses WHERE meeting_key IS NOT NULL
 UNION SELECT a.source_id,cast(p.event_id AS VARCHAR) AS meeting_key,cast(NULL AS VARCHAR) AS chamber
 FROM source_annotation_addresses a JOIN package_records p ON a.package_id=p.package_id
 WHERE NOT a.publisher AND p.event_id IS NOT NULL
)
SELECT source_id,array_sort(array_distinct(array_agg(cast(try_cast(meeting_key AS BIGINT) AS VARCHAR)))) AS meeting_keys,
 array_sort(array_distinct(array_agg(chamber) FILTER(WHERE chamber IS NOT NULL))) AS chambers
FROM combined WHERE try_cast(meeting_key AS BIGINT) IS NOT NULL GROUP BY source_id
