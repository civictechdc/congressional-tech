SELECT body_sha FROM sniff_observations GROUP BY body_sha
HAVING min(format)<>max(format) OR min(intact)<>max(intact)
