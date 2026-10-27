-- DM 7.3. All capture modes contribute literal context addresses.
SELECT sha256
FROM captures
WHERE sha256 IS NOT NULL
GROUP BY sha256
HAVING count(DISTINCT context_url) > 100
