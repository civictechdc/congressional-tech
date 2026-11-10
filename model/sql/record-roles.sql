-- DM 7.3. capture_evidence supplies pinned format/integrity facts and native
-- capture columns. Hash joins carry keys, flags and scalars; titles and text
-- heads remain inside the once-per-body signal step.
WITH roles AS (
    SELECT c.receipt_key, c.receipt_line, c.capture_index, c.sha256, c.format,
        c.intact_basis, c.error_type, c.mode, c.outcome, c.http_status,
        c.complete, c.bytes, p.sha256 AS placeholder_body, l.file_shaped,
        g.receipt_key IS NOT NULL AS good_fetch,
        CASE
            WHEN c.format IS NULL THEN NULL
            WHEN c.format = 'vtt' THEN 'caption'
            WHEN a.sha256 IS NOT NULL THEN 'archive'
            WHEN c.format = 'm3u8' THEN 'playlist'
            -- A stream segment or other unrecognized audio/video body is media, never a document
            -- (senate/players MP2T samples once their stated 200 is read; none listed in v21).
            WHEN c.format = 'other' AND (coalesce(sg.segment, false)
                 OR split_part(lower(c.media_type), '/', 1) IN ('video', 'audio')) THEN 'media'
            WHEN c.format = 'warc' THEN 'envelope'
            WHEN c.format = 'pdf' AND c.intact IS NOT TRUE
                 AND c.intact_basis <> 'unchecked' THEN 'damaged'
            -- JSON here is an API page or a provider's envelope, never a document: all 345 once listed
            -- were, and their contents have their own rows.
            WHEN c.format = 'json' THEN 'api'
            WHEN c.format IN ('html', 'xml', 'json')
                 AND (b.status IS DISTINCT FROM 'completed') THEN NULL
            WHEN c.format = 'xml' AND b.source_record THEN 'source_record'
            WHEN c.format = 'html' AND (b.error_response OR l.error_response)
                 THEN 'error_response'
            WHEN c.format = 'html' AND (b.wrapper OR l.wrapper) THEN 'wrapper'
            WHEN (c.format = 'html' AND b.listing)
                 OR (c.format = 'xml' AND (b.feed OR l.feed)) THEN 'listing'
            ELSE 'document'
        END AS record_role
    FROM archive_bodies a RIGHT JOIN (placeholders p RIGHT JOIN (
        locator_signals l RIGHT JOIN (
            body_signals b RIGHT JOIN (
                segment_captures sg RIGHT JOIN (good_fetch_keys g RIGHT JOIN capture_evidence c
                USING(receipt_key,receipt_line,capture_index))
                ON c.receipt_key = sg.receipt_key AND c.receipt_line = sg.receipt_line
                AND c.capture_index = sg.capture_index
            ) ON c.sha256 = b.body_sha
        ) ON (c.url IS NOT DISTINCT FROM l.url)
            AND (c.requested_url IS NOT DISTINCT FROM l.requested_url)
            AND (c.member_path IS NOT DISTINCT FROM l.member_path)
    ) ON c.sha256 = p.sha256) ON c.sha256 = a.sha256
)
SELECT receipt_key, receipt_line, capture_index, sha256, format, intact_basis,
    error_type, record_role,
    coalesce(
        good_fetch
        AND sha256 IS NOT NULL AND bytes > 0 AND placeholder_body IS NULL
        AND record_role = 'document'
        AND (format <> 'html' OR NOT file_shaped), false
    ) AS is_real_file
FROM roles
