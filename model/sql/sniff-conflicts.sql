SELECT body_sha FROM sniff_observations GROUP BY body_sha
HAVING count(DISTINCT format)>1 OR count(DISTINCT intact)>1
