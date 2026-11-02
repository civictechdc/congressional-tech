-- Retained YouTube Data API responses. Only videoListResponse bodies yield videos (video_records
-- source youtube_api); a channel's uploads playlist omits unlisted videos and some live archives.
WITH api_fetches AS (
 SELECT c.sha256,coalesce(c.stored_suffix,'') AS stored_suffix,c.retrieved_at
 FROM captures c
 WHERE c.family='youtube/api' AND c.mode='fetch' AND c.outcome IN ('stored','unchanged') AND c.sha256 IS NOT NULL
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY sha256 ORDER BY retrieved_at DESC,stored_suffix) AS rn FROM api_fetches
)
SELECT encode(sha256,'hex') AS record_sha,stored_suffix FROM ranked WHERE rn=1
