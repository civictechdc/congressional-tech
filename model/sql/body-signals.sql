-- DM 7.3. page_facts contains the pinned HTML/XML/JSON reading per body.
-- Content patterns and exclusion flags run once per body, independently of capture addresses.
WITH thresholds AS (
    SELECT
        max(CASE WHEN id = 'near_empty' THEN number END) AS near_empty,
        max(CASE WHEN id = 'listing_links' THEN number END) AS listing_links,
        max(CASE WHEN id = 'listing_percent' THEN number END) AS listing_percent
    FROM page_signals
), rules AS (
    SELECT id, kind, pattern, number FROM page_signals
    WHERE kind IN ('source_record_root', 'error_word', 'body_marker', 'wrapper_marker', 'feed_root', 'cover_kind')
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
            ) AS is_qualified_topic_title,
        regexp_like(
            coalesce(text_head, ''),
            '(?is)^\s*(?:memorandum|for\s+immediate\s+release|press\s+release|dear\s+)\b|\b(?:notice\s+of\s+intent\s+to\s+issue\s+a\s+subpoena|authorizing\s+(?:the\s+)?issuance\s+of\s+subpoenas?)\b'
        ) AS is_subpoena_memo,
        regexp_like(coalesce(text_head, ''), '(?is)\broll\s+call\b')
            OR (
                regexp_like(coalesce(text_head, ''), '(?i)\b(?:yeas?|ayes?)\b')
                AND regexp_like(coalesce(text_head, ''), '(?i)\b(?:nays?|noes?)\b')
            ) AS is_roll_call_vote,
        regexp_like(
            coalesce(text_head, ''),
            '(?is)\b(?:markup\s+action\s+sheet|met,\s+pursuant\s+to\s+notice|ordered\s+reported\s+favorably|subpoena)\b'
        ) AS is_markup_action_or_subpoena,
        regexp_like(
            coalesce(text_head, ''),
            '(?is)\b(?:serial\s+no\.|s\.\s*hrg\.|u\.s\.\s+government\s+(?:publishing|printing)\s+office|stenographic\s+transcript)\b'
        ) AS is_gpo_or_steno_hearing,
        regexp_like(
            coalesce(text_head, ''),
            '(?is)\b(?:memorandum|m\s+e\s+m\s+o\s+r\s+a\s+n\s+d\s+u\s+m|(?:staff|majority|minority|subcommittee|committee)\s+memo\b|to\s*:\s*[^\n]{3,160}\s+from\s*:\s*[^\n]{0,120}\b(?:staff|counsel|chairman|chairwoman|chair|ranking\s+member)|congressional\s+distribution\s+memorandum|hearing\s+charter|mark-?up\s+memorandum|testimony\s+(?:before\s+the|of\b)|(?:prepared\s+|written\s+)?statement\s+of\b)\b'
        ) AS is_crs_memo_or_testimony,
        regexp_like(
            coalesce(text_head, ''),
            '(?is)\b(?:1[0-2][0-9]th\s+congress.{0,160}?\b(?:rept\.|report)\b|committed\s+to\s+the\s+committee\s+of\s+the\s+whole\s+house|ordered\s+to\s+be\s+printed)\b'
        ) AS is_committee_report,
        regexp_like(
            coalesce(text_head, ''),
            '(?is)\b(?:re\s*:\s*letter\s+in\s+support|letter\s+(?:in|of)\s+support|dear\s+(?:chairman|chairwoman|chair|senator|senators|representative|representatives|ranking\s+member))\b'
        ) AS is_support_letter,
        regexp_like(
            coalesce(text_head, ''),
            '(?is)\bGAO-[0-9]{2}-[0-9]{3,6}[TR]\b|\btestimony\b'
        ) AS is_gao_testimony_or_corresp,
        regexp_like(
            coalesce(text_head, ''),
            '(?is)\b(?:for\s+immediate\s+release|press\s+release|memorandum|congressional\s+research\s+service|government\s+accountability\s+office|h\.\s*rept\.|s\.\s*rept\.|house\s+report\s+1[0-9]{2}|senate\s+report\s+1[0-9]{2})\b'
        ) AS is_staff_report_excluded
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
            >= max(t.listing_percent) * cast(max(f.text_bytes) AS BIGINT) AS listing,
    substr(min(CASE
        WHEN r.kind = 'cover_kind'
            AND NOT f.is_pdf_magic
            AND coalesce(f.text_bytes, 0) >= 80
            AND CASE r.id
                WHEN 'cover:questionnaire' THEN NOT f.is_support_letter
                WHEN 'cover:subpoena' THEN NOT f.is_subpoena_memo
                WHEN 'cover:attendance-sheet' THEN NOT f.is_roll_call_vote
                WHEN 'cover:meeting-notice' THEN NOT f.is_markup_action_or_subpoena
                WHEN 'cover:witness-list' THEN NOT f.is_gpo_or_steno_hearing
                WHEN 'cover:crs-report' THEN NOT f.is_crs_memo_or_testimony AND NOT f.is_committee_report
                WHEN 'cover:gao-report' THEN NOT f.is_gao_testimony_or_corresp AND NOT f.is_committee_report
                WHEN 'cover:cost-estimate' THEN NOT f.is_crs_memo_or_testimony AND NOT f.is_committee_report
                WHEN 'cover:staff-report' THEN NOT f.is_staff_report_excluded
                ELSE true
            END
            AND coalesce(regexp_like(f.text_head, r.pattern), false)
        THEN lpad(cast(coalesce(r.number, 99) AS VARCHAR), 2, '0') || ':' || substr(r.id, 7)
    END), 4) AS cover_document_kind
FROM rules r CROSS JOIN thresholds t CROSS JOIN facts f
GROUP BY f.body_sha
