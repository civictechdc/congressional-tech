WITH bodies AS (
 SELECT DISTINCT e.endpoint_key,e.member_path,e.body_sha,f.fingerprint
 FROM fingerprints f RIGHT JOIN endpoint_bodies e USING(body_sha)
)
SELECT endpoint_key,member_path FROM bodies GROUP BY endpoint_key,member_path
HAVING count(*)>=2 AND (count(fingerprint)<count(*) OR min(fingerprint)<>max(fingerprint))
