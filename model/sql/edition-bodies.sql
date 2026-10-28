WITH ambiguous AS (
 SELECT DISTINCT e.body_sha FROM endpoint_bodies e
 JOIN (SELECT * FROM ambiguous_endpoints WHERE endpoint_key IS NOT NULL) a
 ON (e.endpoint_key IS NOT DISTINCT FROM a.endpoint_key) AND (e.member_path IS NOT DISTINCT FROM a.member_path)
), known AS (
 SELECT DISTINCT f.fingerprint FROM ambiguous a JOIN fingerprints f USING(body_sha)
 WHERE f.fingerprint IS NOT NULL
)
SELECT body_sha FROM ambiguous
UNION SELECT c.body_sha FROM fingerprint_candidates c JOIN fingerprints f USING(body_sha)
 JOIN known k USING(fingerprint)
