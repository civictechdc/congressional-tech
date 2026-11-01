WITH cache_fetches AS (
 SELECT c.sha256,coalesce(c.stored_suffix,'') AS stored_suffix,c.retrieved_at,
  (regexp_match(coalesce(c.url,c.requested_url),'/(youtube/youtube_[0-9]+[.]json)$'))[1] AS cache_path
 FROM captures c
 -- Git-held pipeline files have no HTTP status, so good means a complete stored fetch.
 WHERE c.family='pipeline-data' AND c.mode='fetch' AND c.complete AND c.outcome IN ('stored','unchanged') AND c.sha256 IS NOT NULL
  AND regexp_like(coalesce(c.url,c.requested_url),'/youtube/youtube_[0-9]+[.]json$')
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY cache_path ORDER BY retrieved_at DESC,sha256) AS rn FROM cache_fetches
)
SELECT cache_path,encode(sha256,'hex') AS record_sha,stored_suffix FROM ranked WHERE rn=1
