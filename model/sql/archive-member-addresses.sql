-- DM 7.2. A member of a container whose layout mirrors its server directory is
-- also published at prefix + member path, when the member's first segment is
-- the container's own name. Sources keep the container URL and member path.
SELECT DISTINCT c.source_id,c.body_sha,l.published_prefix||c.member_path AS published_url
FROM archive_layouts l JOIN capture_source_contexts c
 ON regexp_like(c.context_url,l.container_pattern) AND regexp_like(c.member_path,l.member_pattern)
WHERE c.outcome NOT IN ('reference','saved-record') AND c.body_sha IS NOT NULL
 AND (regexp_match(c.context_url,l.container_pattern))[1]=(regexp_match(c.member_path,l.member_pattern))[1]
