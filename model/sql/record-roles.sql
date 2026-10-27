-- DM 7.3. capture_evidence supplies pinned format/integrity facts and native
-- capture columns. Hash joins carry keys, flags and scalars; titles and text
-- heads remain inside the once-per-body signal step.
WITH roles AS (
    SELECT c.receipt_key, c.receipt_line, c.capture_index, c.sha256, c.format,
        c.intact_basis, c.error_type, c.mode, c.outcome, c.attempt_status,
        c.complete, c.bytes, p.sha256 AS placeholder_body, l.file_shaped,
        CASE
            WHEN c.format IS NULL THEN NULL
            WHEN c.format = 'vtt' THEN 'caption'
            WHEN c.format = 'm3u8' THEN 'playlist'
            WHEN c.format = 'warc' THEN 'envelope'
            WHEN c.format = 'pdf' AND c.intact IS NOT TRUE
                 AND c.intact_basis <> 'unchecked' THEN 'damaged'
            WHEN c.format = 'json' AND l.api THEN 'api'
            WHEN c.format IN ('html', 'xml', 'json')
                 AND (b.status IS DISTINCT FROM 'completed') THEN NULL
            WHEN c.format = 'xml' AND b.source_record THEN 'source_record'
            WHEN c.format = 'html' AND (b.error_response OR l.error_response)
                 THEN 'error_response'
            WHEN c.format = 'html' AND b.wrapper THEN 'wrapper'
            WHEN (c.format = 'html' AND b.listing)
                 OR (c.format = 'xml' AND (b.feed OR l.feed)) THEN 'listing'
            ELSE 'document'
        END AS record_role
    FROM capture_evidence c
    LEFT JOIN body_signals b ON c.sha256 = b.body_sha
    LEFT JOIN locator_signals l ON (c.url IS NOT DISTINCT FROM l.url)
        AND (c.member_path IS NOT DISTINCT FROM l.member_path)
    LEFT JOIN placeholders p ON c.sha256 = p.sha256
)
SELECT receipt_key, receipt_line, capture_index, sha256, format, intact_basis,
    error_type, record_role,
    coalesce(
        mode = 'fetch' AND complete AND outcome IN ('stored', 'unchanged')
        AND attempt_status BETWEEN 200 AND 299
        AND sha256 IS NOT NULL AND bytes > 0 AND placeholder_body IS NULL
        AND record_role = 'document'
        AND (format <> 'html' OR NOT file_shaped), false
    ) AS is_real_file
FROM roles
