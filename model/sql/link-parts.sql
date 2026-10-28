SELECT href,repair_matches,unnest(parts) AS target_literal,
 unnest(range(0,cast(array_length(parts) AS BIGINT))) AS split_position
FROM link_literals
