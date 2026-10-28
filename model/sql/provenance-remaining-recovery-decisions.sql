WITH remaining AS (
 SELECT r.* FROM recovery_decisions r WHERE NOT EXISTS (
 SELECT 1 FROM recovery_decisions s WHERE s.supersedes=r.id)
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY lower(body_sha256),original_url
 ORDER BY cast(decided_at AS TIMESTAMP WITH TIME ZONE) DESC,id DESC) AS selected FROM remaining
)
SELECT * FROM ranked WHERE selected=1
