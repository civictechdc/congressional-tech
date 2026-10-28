WITH remaining AS (
 SELECT r.* FROM rendition_members r
 LEFT ANTI JOIN edition_bodies e USING(body_sha)
), invalid AS (
 SELECT group_kind,group_id FROM remaining GROUP BY group_kind,group_id,format
 HAVING min(body_sha)<>max(body_sha)
), multiple AS (
 SELECT group_kind,group_id FROM remaining GROUP BY group_kind,group_id
 HAVING min(body_sha)<>max(body_sha)
)
SELECT r.* FROM remaining r JOIN multiple m USING(group_kind,group_id)
 LEFT ANTI JOIN invalid i USING(group_kind,group_id)
