-- Unrecognized ('other') bodies whose address is a stream segment by the recording
-- registry's own segment pattern; legacy rows carry no media type. Few rows (48 in v21).
SELECT DISTINCT c.receipt_key, c.receipt_line, c.capture_index, true AS segment
FROM capture_evidence c JOIN recording_sources s ON s.kind = 'segment_exclusion'
    AND regexp_like(coalesce(c.url, c.requested_url, c.context_url), s.pattern)
WHERE c.format = 'other'
