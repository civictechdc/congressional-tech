-- DM3: only endpoint multiplicity makes a body a fingerprint candidate.
WITH multiple AS (
 SELECT endpoint_key,member_path FROM endpoint_bodies
 GROUP BY endpoint_key,member_path HAVING count(DISTINCT body_sha)>=2
)
SELECT DISTINCT e.body_sha FROM endpoint_bodies e JOIN multiple m
 ON e.endpoint_key=m.endpoint_key AND e.member_path IS NOT DISTINCT FROM m.member_path
