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
        row_number() OVER (PARTITION BY q.input_id
            ORDER BY q.url_priority, p.priority, q.part_index) AS preference
    FROM filename_parameters p JOIN query_parts q
        ON lower(percent_decode_utf8(split_part(q.part, '=', 1))) = p.parameter
)
SELECT i.input_id, i.source_url,
    coalesce(
        CASE WHEN i.recovery_rejected IS NOT TRUE THEN nullif(i.recovered_filename, '') END,
        nullif(regexp_replace(i.member_path, '^.*/', ''), ''),
        nullif(disposition_filename(i.h_content_disposition), ''),
        nullif(p.filename, ''),
        nullif(url_filename(i.source_url), ''),
        nullif(url_filename(i.requested_url), ''), '') AS filename
FROM parameter_values p RIGHT JOIN filename_inputs i
    ON i.input_id = p.input_id AND p.preference = 1
