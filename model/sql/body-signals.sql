-- DM 7.3. page_facts contains the pinned HTML/XML/JSON reading per body.
-- Content patterns run once per body, independently of capture addresses.
WITH thresholds AS (
    SELECT
        max(CASE WHEN id = 'near_empty' THEN number END) AS near_empty,
        max(CASE WHEN id = 'listing_links' THEN number END) AS listing_links,
        max(CASE WHEN id = 'listing_percent' THEN number END) AS listing_percent
    FROM page_signals
), rules AS (
    SELECT kind, pattern FROM page_signals
    WHERE kind IN ('source_record_root', 'error_word', 'body_marker', 'wrapper_marker', 'feed_root')
      AND pattern IS NOT NULL
), facts AS (
    SELECT body_sha,status,xml_root,title,heading,text_head,text_bytes,link_count,link_text_bytes
    FROM page_facts
)
SELECT f.body_sha, max(f.status) AS status,
    bool_or(CASE WHEN r.kind = 'source_record_root'
        THEN coalesce(regexp_like(f.xml_root, r.pattern), false) ELSE false END) AS source_record,
    bool_or(CASE
        WHEN r.kind = 'error_word' THEN coalesce(
            regexp_like(f.title, r.pattern) OR regexp_like(f.heading, r.pattern), false)
        WHEN r.kind = 'body_marker' THEN coalesce(regexp_like(f.text_head, r.pattern), false)
        ELSE false END) OR max(f.text_bytes) < max(t.near_empty) AS error_response,
    bool_or(CASE WHEN r.kind = 'wrapper_marker'
        THEN coalesce(regexp_like(f.text_head, r.pattern), false) ELSE false END) AS wrapper,
    bool_or(CASE WHEN r.kind = 'feed_root'
        THEN coalesce(regexp_like(f.xml_root, r.pattern), false) ELSE false END) AS feed,
    max(f.link_count) >= max(t.listing_links)
        AND 100 * cast(max(f.link_text_bytes) AS BIGINT)
            >= max(t.listing_percent) * cast(max(f.text_bytes) AS BIGINT) AS listing
FROM rules r CROSS JOIN thresholds t CROSS JOIN facts f
GROUP BY f.body_sha
