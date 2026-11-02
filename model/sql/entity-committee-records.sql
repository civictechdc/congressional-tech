WITH selected AS (
 SELECT record_sha,try_cast(event_id AS BIGINT) AS event_id,updated,records
 FROM selected_committee_records
 WHERE status='completed' AND event_id IS NOT NULL
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY event_id ORDER BY updated DESC NULLS LAST,encode(record_sha,'hex')) AS rn FROM selected
), expanded AS (
 SELECT event_id,record_sha,unnest(records) AS r FROM ranked WHERE rn=1
)
SELECT encode(sha256(json_array(encode(record_sha,'hex'),cast(r['ordinal'] AS VARCHAR))),'hex') AS record_key,
 event_id,
 r['kind'] AS kind,
 r['bill'] AS bill,
 r['number'] AS number,
 r['sponsor_bioguide'] AS sponsor_bioguide,
 r['amendment_type'] AS amendment_type,
 r['enbloc'] AS enbloc,
 r['description'] AS source_description,
 r['url'] AS url,
 record_sha,
 r['ordinal'] AS ordinal
FROM expanded
