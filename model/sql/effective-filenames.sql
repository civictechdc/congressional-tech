-- DM 7.4. One caller-supplied input_id per capture or recovery original link.
-- filename_parameters holds ordered parameter names; URL decoding preserves +.
WITH urls AS (
    SELECT input_id,
        unnest(make_array(source_url, requested_url)) AS candidate_url,
        unnest(make_array(0, 1)) AS url_priority
    FROM filename_inputs
), queries AS (
    SELECT input_id, url_priority,
        CASE WHEN strpos(split_part(candidate_url, '#', 1), '?') > 0
            THEN substr(split_part(candidate_url, '#', 1),
                        strpos(split_part(candidate_url, '#', 1), '?') + 1)
            ELSE '' END AS query
    FROM urls WHERE candidate_url IS NOT NULL
), query_parts AS (
    SELECT input_id, url_priority,
        unnest(string_to_array(query, '&')) AS part,
        unnest(range(0, cast(array_length(string_to_array(
            query, '&')) AS BIGINT))) AS part_index
    FROM queries
), parameter_values AS (
    SELECT q.input_id,
        percent_decode_utf8(CASE WHEN strpos(q.part, '=') > 0
            THEN substr(q.part, strpos(q.part, '=') + 1) ELSE '' END) AS filename,
        q.url_priority,
        row_number() OVER (PARTITION BY q.input_id
            ORDER BY q.url_priority, p.priority, q.part_index) AS preference,
        row_number() OVER (PARTITION BY q.input_id, q.url_priority
            ORDER BY p.priority, q.part_index) AS url_preference
    FROM filename_parameters p JOIN query_parts q
        ON lower(percent_decode_utf8(split_part(q.part, '=', 1))) = p.parameter
), named AS (
SELECT i.input_id, i.source_url, i.requested_url, i.member_path,
    coalesce(
        CASE WHEN i.recovery_rejected IS NOT TRUE THEN nullif(i.recovered_filename, '') END,
        nullif(regexp_replace(i.member_path, '^.*/', ''), ''),
        nullif(disposition_filename(i.h_content_disposition), ''),
        nullif(p.filename, ''),
        nullif(url_filename(i.source_url), ''),
        nullif(url_filename(i.requested_url), ''),
        -- A capture with no URL of its own is published at its context address.
        nullif(url_filename(i.context_url), ''),
        -- A query-free URL ending in '/' names its last non-empty path segment.
        nullif(CASE WHEN strpos(i.source_url, '?') = 0
            THEN url_filename(regexp_replace(i.source_url, '/+(#.*)?$', '')) END, ''),
        nullif(CASE WHEN strpos(i.requested_url, '?') = 0
            THEN url_filename(regexp_replace(i.requested_url, '/+(#.*)?$', '')) END, ''),
        nullif(CASE WHEN strpos(i.context_url, '?') = 0
            THEN url_filename(regexp_replace(i.context_url, '/+(#.*)?$', '')) END, ''), '') AS filename,
    -- The requested (linked) URL's own name, by the same URL rules (owner, 2026-11-02: read both
    -- names). The shown name stays the one above; this second name is read only for the facts
    -- the shown name lacks or contradicts (source-annotations-filename.sql).
    coalesce(nullif(r.filename, ''), nullif(url_filename(i.requested_url), ''),
        nullif(CASE WHEN strpos(i.requested_url, '?') = 0
            THEN url_filename(regexp_replace(i.requested_url, '/+(#.*)?$', '')) END, '')) AS requested_name
FROM parameter_values r RIGHT JOIN (parameter_values p RIGHT JOIN filename_inputs i
    ON i.input_id = p.input_id AND p.preference = 1)
    ON i.input_id = r.input_id AND r.url_priority = 1 AND r.url_preference = 1
)
-- A requested name is kept only for a top-level capture whose requested URL differs from its
-- source URL and names it differently: redirects to a final URL, nothing else.
SELECT input_id, source_url, filename,
    CASE WHEN member_path IS NULL AND (requested_url IS DISTINCT FROM source_url)
        AND (requested_name IS DISTINCT FROM filename) THEN requested_name END AS requested_filename,
    CASE WHEN member_path IS NULL AND (requested_url IS DISTINCT FROM source_url)
        AND (requested_name IS DISTINCT FROM filename) AND requested_name IS NOT NULL THEN requested_url END AS requested_url
FROM named
