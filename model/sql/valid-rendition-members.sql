WITH remaining AS (
 SELECT r.* FROM edition_bodies e
 RIGHT ANTI JOIN rendition_members r USING(body_sha)
), invalid AS (
 SELECT group_kind,group_id FROM remaining GROUP BY group_kind,group_id,format
 HAVING min(body_sha)<>max(body_sha)
), multiple AS (
 SELECT group_kind,group_id FROM remaining GROUP BY group_kind,group_id
 HAVING min(body_sha)<>max(body_sha)
)
SELECT r.* FROM invalid i RIGHT ANTI JOIN (multiple m JOIN remaining r USING(group_kind,group_id))
 USING(group_kind,group_id)
