-- DM 7.3. capture_locators is the distinct (url, member_path) relation.
-- URL-dependent rules remain separate from facts about a response body.
WITH rules AS (
    SELECT kind, pattern FROM page_signals
    WHERE kind IN ('error_url', 'api_endpoint', 'feed_url') AND pattern IS NOT NULL
    UNION ALL
    SELECT 'file_shape' AS kind, pattern FROM file_shapes
)
SELECT c.url, c.member_path,
    bool_or(CASE WHEN r.kind = 'api_endpoint'
        THEN coalesce(regexp_like(c.url, r.pattern), false) ELSE false END) AS api,
    bool_or(CASE WHEN r.kind = 'error_url'
        THEN coalesce(regexp_like(c.url, r.pattern), false) ELSE false END) AS error_response,
    bool_or(CASE WHEN r.kind = 'feed_url'
        THEN coalesce(regexp_like(c.url, r.pattern), false) ELSE false END) AS feed,
    bool_or(CASE WHEN r.kind = 'file_shape'
        THEN coalesce(regexp_like(coalesce(c.member_path, c.url), r.pattern), false)
        ELSE false END) AS file_shaped
FROM capture_locators c CROSS JOIN rules r
GROUP BY c.url, c.member_path
