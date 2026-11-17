WITH enabled AS (
 SELECT 1 AS on_flag FROM parser_versions WHERE parser='html_metadata' LIMIT 1
), html_bodies AS (
 SELECT sf.body_sha
 FROM enabled
 CROSS JOIN (SELECT DISTINCT body_sha FROM sniff_facts WHERE format='html') sf
 JOIN profile_bodies b ON sf.body_sha=b.body_sha
), settled AS (
 SELECT r.body_sha FROM selected_readings r
 WHERE r.parser='html_metadata' AND r.status IN ('completed','partial','error','size_limit')
 UNION
 SELECT arrow_cast(decode(u.body_sha256,'hex'),'FixedSizeBinary(32)') AS body_sha
 FROM active_unreadable u
 JOIN accepted_versions v ON u.parser=v.parser AND u.parser_version=v.version
 WHERE u.parser='html_metadata' AND u.body_sha256 IS NOT NULL AND length(u.body_sha256)=64
)
SELECT count(*) AS cnt
FROM settled s
RIGHT ANTI JOIN html_bodies h ON s.body_sha=h.body_sha
