-- The one selection of a record table's pinned parser versions; old and new copies never compete.
-- An equality key exists: a pinned job selects by (parser, version). Only an unpinned job takes all.
WITH pinned AS (
 SELECT DISTINCT parser,version FROM parser_versions WHERE parser LIKE '{{TABLE}}.%'
)
SELECT r.*
FROM {{INPUT}} r
JOIN pinned v ON v.parser=concat('{{TABLE}}.',r.source) AND v.version=r.parser_version
UNION ALL
SELECT r.*
FROM {{INPUT}} r
WHERE (SELECT count(*) FROM pinned)=0
