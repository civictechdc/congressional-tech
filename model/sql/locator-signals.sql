-- DM 7.3. capture_locators is the distinct (url, member_path) relation.
-- URL-dependent rules remain separate from facts about a response body.
WITH rules AS (
    SELECT kind, pattern FROM page_signals
    WHERE kind IN ('error_url', 'api_endpoint', 'feed_url', 'wrapper_url', 'landing_url') AND pattern IS NOT NULL
    UNION ALL
    SELECT 'file_shape' AS kind, pattern FROM file_shapes
)
-- A redirect is judged by both addresses (red-e1b): an error address at either end is an
-- error, and a file-shaped request stays file-shaped unless it landed on an error address.
SELECT c.url, c.requested_url, c.member_path,
    bool_or(CASE WHEN r.kind = 'api_endpoint'
        THEN coalesce(regexp_like(c.url, r.pattern), false) ELSE false END) AS api,
    bool_or(CASE WHEN r.kind = 'error_url'
        THEN coalesce(regexp_like(c.url, r.pattern), false)
          OR coalesce(regexp_like(c.requested_url, r.pattern), false) ELSE false END) AS error_response,
    bool_or(CASE WHEN r.kind = 'feed_url'
        THEN coalesce(regexp_like(c.url, r.pattern), false) ELSE false END) AS feed,
    -- An address whose page only leads elsewhere, such as a site's help page (ct-aoxp) or a landing
    -- page that describes one file (ct-m878, landing-pages.sql), judged by the address that answered.
    bool_or(CASE WHEN r.kind IN ('wrapper_url', 'landing_url')
        THEN coalesce(regexp_like(c.url, r.pattern), false) ELSE false END) AS wrapper,
    bool_or(CASE WHEN r.kind = 'file_shape'
        THEN coalesce(regexp_like(coalesce(c.member_path, c.url), r.pattern), false)
        ELSE false END)
    OR (c.member_path IS NULL
        AND bool_or(CASE WHEN r.kind = 'file_shape'
            THEN coalesce(regexp_like(c.requested_url, r.pattern), false) ELSE false END)
        AND NOT bool_or(CASE WHEN r.kind = 'error_url'
            THEN coalesce(regexp_like(c.url, r.pattern), false) ELSE false END)) AS file_shaped
FROM rules r CROSS JOIN capture_locators c
GROUP BY c.url, c.requested_url, c.member_path
