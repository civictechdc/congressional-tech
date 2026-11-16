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
    SELECT body_sha,status,xml_root,title,heading,text_head,text_bytes,link_count,link_text_bytes,
        starts_with(ltrim(coalesce(text_head, '')), '%PDF-') AS is_pdf_magic,
        coalesce(text_bytes, 0) >= 1000
            AND regexp_like(
                coalesce(title, heading, ''),
                '(?i)^\s*(?:(?:hearing|oversight\s+hearing|subcommittee\s+hearing|roundtable|markup|forum)\s+(?:on|entitled)\s+["“'']?)?(?:access\s+denied|[^\n:|–—]{2,40}\berror\b)\s*:\s+[a-z0-9"“''$]{3,}'
            )
            AND NOT regexp_like(
                coalesce(heading, ''),
                '(?i)^\s*(?:access\s+denied|403\b.*|404\b.*|forbidden|page\s+not\s+found|not\s+found|error|service\s+unavailable|just\s+a\s+moment.*|attention\s+required.*|request\s+not\s+accepted.*)\s*$'
            )
            AND NOT regexp_like(
                coalesce(title, ''),
                '(?i)^\s*(?:access\s+denied|403\b[^:]*|404\b[^:]*|forbidden|page\s+not\s+found|not\s+found|error|service\s+unavailable|just\s+a\s+moment|attention\s+required|checking\s+your\s+browser|client\s+challenge|request\s+not\s+accepted)\s*(?:[|—–-]|$)'
            )
            AND NOT regexp_like(
                coalesce(text_head, ''),
                '(?i)not\s+authorized\s+to\s+access|don[''’]t\s+have\s+permission\s+to\s+access|access\s+to\s+this\s+page\s+has\s+been\s+denied|\b403\s+forbidden\b|\b404\s+not\s+found\b|security\s+risk\s+detected'
            )
            AND regexp_like(
                concat_ws(' ', title, heading, text_head),
                '(?i)\b(?:hearing|markup|testimony|subcommittee|committee\s+on|congressional\s+(?:research\s+service|budget\s+office)|government\s+accountability\s+office)\b'
            ) AS is_qualified_topic_title
    FROM page_facts
)
SELECT f.body_sha, max(f.status) AS status,
    bool_or(CASE WHEN r.kind = 'source_record_root'
        THEN coalesce(regexp_like(f.xml_root, r.pattern), false) ELSE false END) AS source_record,
    bool_or(CASE
        WHEN f.is_pdf_magic THEN false
        WHEN r.kind = 'error_word' THEN coalesce(
            (regexp_like(f.title, r.pattern) OR regexp_like(f.heading, r.pattern))
            AND NOT f.is_qualified_topic_title,
            false
        )
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
